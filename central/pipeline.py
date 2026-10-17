"""One pinned case through matching, assessment, optional review, and append-only output."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from .candidates import build_candidates
from .combine import combine
from .decisions import (apply_interpretation_decisions, bind_property_targets, load_decisions,
                        prepare_assignments, reviewed_report)
from .output import CombinedOutput, identify_issues, write_run


def _snapshot(path: Path) -> tuple[Path, bytes]:
    resolved = path.resolve(strict=True)
    return resolved, resolved.read_bytes()


def _case_folder(source_path: str, case_id: str, root: Path) -> Path:
    path = Path(source_path)
    if path.parent.name != case_id:
        raise ValueError("source path does not identify the requested preprocess case folder")
    return (path if path.is_absolute() else root / path).parent.resolve()


def _stable_order(interpretation: dict, reference: dict) -> None:
    """A property edit does not silently renumber REDCap lesion instances."""
    prior = {lesion.get("focus") or lesion.get("source_identity") or lesion.get("source_subject"): lesion for lesion in reference["lesions"]}
    remap = {}
    for lesion in interpretation["lesions"]:
        old = prior.get(lesion.get("focus") or lesion.get("source_identity") or lesion.get("source_subject"))
        if old:
            remap[lesion["id"]] = old["id"]
            lesion.update(id=old["id"], order=old["order"])
    interpretation["lesions"].sort(key=lambda lesion: lesion["order"])
    for issue in interpretation["issues"]:
        issue["context"] = [remap.get(ref, ref) for ref in issue.get("context", [])]


def _complete_lineage(interpretation: dict, matching: dict, candidates: list[dict], decisions: list[dict]) -> None:
    """Materialize drawing-backed and non-tumour hypotheses with every membership retained."""
    index = {candidate["id"]: candidate for candidate in candidates}
    rejected = {"group:" + d["target"]["group"].removeprefix("group:"): d["id"]
                for d in decisions if d["kind"] == "reject_group"}
    for lesion in [*interpretation["lesions"], *interpretation["other_findings"]]:
        other = lesion["kind"] == "other finding"
        if ((not other and lesion.get("focus"))
                or len(lesion.get("marks", [])) < (1 if other else 2)):
            continue
        lesion["source_identity"] = lesion.pop("source_subject", lesion.get("source_identity"))
        hid = "h-drawing-" + lesion["id"]
        memberships = ([{"subject": lesion["source_identity"], "role": "report description",
                         "supports": [ref for prop in lesion["properties"] for ref in prop.get("supports", [])],
                         "depends_on": [], "certainty": "low", "review_status": "unreviewed", "opposes": [],
                         "rationale": "The report identifies this non-tumour finding."}] if other else [])
        reassess = []
        for cid in lesion["candidates"]:
            candidate = index[cid]
            dependencies = candidate.get("depends_on", [])
            reassess.extend(rejected[ref] for ref in dependencies if ref in rejected)
            memberships.extend({"subject": mark, "role": "diagram depiction", "supports": [mark],
                                "depends_on": dependencies, "certainty": "low",
                                "opposes": [], "rationale": "Membership follows the drawing candidate; identity remains provisional.",
                                "review_status": "needs_review" if reassess else "unreviewed"}
                               for mark in candidate["marks"])
        matching["hypotheses"].append({"id": hid, "focus": None, "candidates": lesion["candidates"],
                                       "memberships": memberships, "certainty": "low", "brain": "rules",
                                       "supports": lesion.get("supports", [ref for prop in lesion["properties"] for ref in prop.get("supports", [])]),
                                       "review_status": "needs_review" if reassess else "unreviewed",
                                       "opposing_considerations": ["The reviewer rejected a supporting drawing group."] if reassess else [],
                                       "assumptions": ["The drawing candidate depicts one finding; identity requires review."],
                                       "rationale": "Compatible non-tumour location." if other else "Provisional drawing group, supported by the specimen count or multifocality statement."})
        lesion["hypothesis"] = hid
        if reassess:
            lesion["identity_disposition"] = "unresolved"
            lesion["review_status"] = "needs_review"
            interpretation["issues"].append({"kind": "other", "severity": "question", "context": [lesion["id"], hid],
                                              "reason": "The rejected drawing group requires reassessment of these memberships.",
                                              "depends_on": ["decision:" + ident for ident in sorted(set(reassess))]})


def _review_provenance(value, effective_report: dict) -> None:
    changes = {obs["id"]: "decision:" + obs["review_decision"] for obs in effective_report["extraction"]["observations"]
               if obs.get("review_decision")}
    changes.update({"report:" + ident: decision for ident, decision in list(changes.items())})

    def visit(node):
        if isinstance(node, dict):
            for key, item in list(node.items()):
                if key in {"supports", "inputs", "context", "derived_from"} and isinstance(item, list):
                    revised = [changes.get(ref, ref) if isinstance(ref, str) else ref for ref in item]
                    if revised != item:
                        node.setdefault("source_inputs", []).extend(ref for ref in item if isinstance(ref, str) and ref in changes)
                        node[key] = revised
                elif key in {"report_ref", "ref"} and isinstance(item, str) and item in changes:
                    node["source_" + key] = item
                    node[key] = changes[item]
                else:
                    visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)
    visit(value)


def run_case(case_id: str, *, root: Path | None = None, report_path: Path | None = None,
             drawing_path: Path | None = None, decisions_path: Path | None = None,
             previous_path: Path | None = None, use_llm: bool = True, transport=None) -> Path:
    """Read each input once for this run, validate it, and record its exact file hash."""
    from .checks import run_checks
    from .inputs import load_drawing, load_report
    from .lesions import build_interpretation
    from .llm import run_llm, unavailable_llm
    from .matching import match

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", case_id):
        raise ValueError("case ID must be a single safe folder name")
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    case_dir = root / "Other/output/combined" / case_id
    report_file, report_bytes = _snapshot(report_path or root / "Other/output/report" / case_id / "report.json")
    drawing_file, drawing_bytes = _snapshot(drawing_path or root / "Other/output/drawing" / case_id / "drawing.json")
    report, drawing = load_report(report_file), load_drawing(drawing_file)
    if report_file.read_bytes() != report_bytes or drawing_file.read_bytes() != drawing_bytes:
        raise ValueError("an input changed during validation; retry with stable files")
    if drawing["extraction"]["case_id"] != case_id:
        raise ValueError("drawing case_id does not match the requested preprocess case")
    report_folder = _case_folder(report["document"]["source_path"], case_id, root)
    drawing_folder = _case_folder(drawing["extraction"]["source_path"], case_id, root)
    if report_folder != drawing_folder:
        raise ValueError("report and drawing are not from the same supplied preprocess case folder")
    report_hash, drawing_hash = (hashlib.sha256(data).hexdigest() for data in (report_bytes, drawing_bytes))
    decisions_file = decisions_path or case_dir / "decisions.json"
    decision_snapshot = _snapshot(decisions_file) if decisions_file.exists() else None
    decisions = load_decisions(decision_snapshot[0] if decision_snapshot else None)
    if decision_snapshot and decision_snapshot[0].read_bytes() != decision_snapshot[1]:
        raise ValueError("decisions changed while loading")

    previous, previous_run = None, None
    prior_path = previous_path or case_dir / "latest/combined.json"
    if prior_path.exists() and decision_snapshot:
        prior_file, prior_bytes = _snapshot(prior_path)
        previous = CombinedOutput.model_validate_json(prior_bytes).model_dump(mode="json")
        if previous["case_id"] != case_id:
            raise ValueError("previous run belongs to another case")
        previous_run = prior_file.parent.name
    same_inputs = bool(previous and previous["inputs"]["report"]["sha256"] == report_hash
                       and previous["inputs"]["drawing"]["sha256"] == drawing_hash)
    if previous:
        history = {decision["id"]: decision for decision in (previous.get("decisions_history") or previous["decisions_applied"])}
        for entry in decisions:
            prior = history.get(entry["id"])
            if prior and entry["kind"] == "set_value":
                for key in ("focus", "mark"):
                    if prior["target"].get(key):
                        entry["target"][key] = prior["target"][key]
            history[entry["id"]] = entry
        decisions = list(history.values())

    candidates = build_candidates(drawing)
    matching = match(report, candidates)
    initial_interpretation = build_interpretation(report, drawing, candidates, matching)
    decision_history = []
    decisions, binding_issues = bind_property_targets(decisions, initial_interpretation, previous,
                                                      history=decision_history)
    prior_rules_matching = previous["brains"]["rules"].get("matching", previous["matching"]) if same_inputs else None
    touched, decision_issues, applied = set(), [], []
    rerun = bool(previous and decision_snapshot)
    if decisions or same_inputs:
        baseline = previous if same_inputs else {"matching": matching, "candidates": candidates}
        candidates, fixed, touched, decision_issues, applied = prepare_assignments(
            report, drawing, candidates, baseline, decisions)
        matching = match(report, candidates, fixed_assignment=fixed,
                         previous_matching=prior_rules_matching)
    source_interpretation = build_interpretation(report, drawing, candidates, matching)
    effective_report = reviewed_report(report, source_interpretation, decisions)
    if effective_report != report:
        matching = match(effective_report, candidates, fixed_assignment=matching["best_assignment"],
                         previous_matching=matching)
    interpretation = build_interpretation(effective_report, drawing, candidates, matching)
    _stable_order(interpretation, previous if same_inputs else source_interpretation)
    sector_decisions = [decision for decision in decisions
                        if decision["kind"] == "set_value" and decision["target"]["property"] == "sectors"]
    if sector_decisions:
        from .candidates import crosswalk_rows
        from .issues import filter_signals
        interpretation, _, _ = apply_interpretation_decisions(
            interpretation, sector_decisions, source_interpretation=source_interpretation)
        interpretation["issues"] = [issue for issue in interpretation["issues"] if "signal" not in issue]
        signals, details = filter_signals(drawing, interpretation["lesions"], candidates, crosswalk_rows())
        interpretation["issues"].extend(signals)
        interpretation["details"] = details
    interpretation["issues"].extend(decision_issues)
    interpretation["issues"].extend(binding_issues)
    interpretation["issues"].extend(run_checks(effective_report, interpretation["lesions"], candidates))
    _review_provenance(interpretation, effective_report)
    _review_provenance(matching, effective_report)
    rules_brain = {"version": "rules-1", "assignment": deepcopy(matching.get("best_assignment", {})),
                   "matching": deepcopy(matching), "issues": identify_issues(deepcopy(interpretation["issues"]))}

    if rerun:
        llm = deepcopy(previous["brains"]["llm"])
        llm.setdefault("input_hashes", {name: previous["inputs"][name]["sha256"] for name in ("report", "drawing")}
                       if llm.get("input_hashes_match", True) else {})
        llm["before_decisions"] = True
        llm["input_hashes_match"] = llm["input_hashes"] == {"report": report_hash, "drawing": drawing_hash}
        if not llm["input_hashes_match"]:
            # Its old input reading remains visible, but contributes nothing to this new attempt.
            touched.update(lesion["id"] for lesion in interpretation["lesions"])
            touched.update(lesion.get("focus", "") for lesion in interpretation["lesions"])
    elif use_llm:
        llm = run_llm(report, drawing, transport=transport)
    else:
        llm = unavailable_llm(report, drawing, "LLM disabled for this offline run.")
    if not rerun:
        llm["input_hashes"] = {"report": report_hash, "drawing": drawing_hash}
        llm["input_hashes_match"] = True

    # Property edits also remove the old LLM opinion before combining confidence.
    touched.update(decision["target"]["lesion"] for decision in decisions
                   if decision["kind"] == "set_value")
    prior_issues = {issue["id"]: issue for issue in (previous or {}).get("issues", [])}
    for decision in decisions:
        if decision["kind"] == "resolve_issue":
            prior_issue = prior_issues.get(decision["target"]["issue"], {})
            if prior_issue.get("kind") == "matcher_disagreement":
                touched.update(prior_issue.get("context", []))
    if same_inputs:
        touched.update(mark for lesion in previous["lesions"]
                       if lesion.get("focus") in touched or lesion["id"] in touched
                       for mark in lesion.get("marks", []))
    active_llm = llm if llm["input_hashes_match"] else {
        "status": "missing", "error": "Prior LLM reading belongs to different input hashes and is retained only as history."}
    interpretation, matching = combine(interpretation, matching, active_llm, touched=touched)
    if same_inputs:
        affected = set(touched)
        for lesion in interpretation["lesions"]:
            if lesion.get("focus") in touched:
                affected.add(lesion["id"])
        for old_issue in previous["issues"]:
            if old_issue["kind"] == "matcher_disagreement" and affected.intersection(old_issue.get("context", [])):
                relevant = []
                for decision in decisions:
                    target = decision["target"]
                    refs = {value for key, value in target.items() if key in {"focus", "lesion", "mark"} and value}
                    if target.get("group"):
                        group = "group:" + target["group"].removeprefix("group:")
                        refs.update(mark for candidate in previous["candidates"]
                                    if group in candidate.get("depends_on", []) for mark in candidate["marks"])
                    for lesion in previous["lesions"]:
                        if refs.intersection({lesion["id"], lesion.get("focus"), *lesion.get("marks", [])}):
                            refs.update({lesion["id"], lesion.get("focus"), *lesion.get("marks", [])})
                    if ((decision["kind"] == "resolve_issue" and target["issue"] == old_issue["id"])
                            or (decision["kind"] != "resolve_issue" and refs.intersection(old_issue.get("context", [])))):
                        relevant.append(decision)
                if not relevant:
                    continue
                resolved = deepcopy(old_issue)
                resolved.update(status="resolved", resolved_by=[d["id"] for d in relevant],
                                decision=deepcopy(relevant[-1]), decision_records=deepcopy(relevant))
                interpretation["issues"].append(resolved)
    interpretation["issues"] = identify_issues(interpretation["issues"])
    if same_inputs:
        current_issue_ids = {issue["id"] for issue in interpretation["issues"]}
        for decision in decisions:
            if decision["kind"] == "resolve_issue":
                ident = decision["target"]["issue"]
                if ident in prior_issues and ident not in current_issue_ids:
                    interpretation["issues"].append(deepcopy(prior_issues[ident]))
                    current_issue_ids.add(ident)
    interpretation, property_touched, property_applied = apply_interpretation_decisions(
        interpretation, decisions, source_interpretation=source_interpretation)
    if same_inputs:
        prior_lesions = {lesion["id"]: lesion for lesion in previous["lesions"]}
        for index, lesion in enumerate(interpretation["lesions"]):
            if lesion["id"] not in touched | property_touched and lesion.get("focus") not in touched | property_touched:
                if lesion["id"] in prior_lesions:
                    interpretation["lesions"][index] = deepcopy(prior_lesions[lesion["id"]])
    _complete_lineage(interpretation, matching, candidates, decisions)
    interpretation["issues"] = identify_issues(interpretation["issues"])
    applied = {decision["id"]: decision for decision in [*applied, *property_applied]}
    inputs = {
        "report": {"path": str(report_file), "sha256": report_hash, "extraction_id": report["extraction"]["id"]},
        "drawing": {"path": str(drawing_file), "sha256": drawing_hash,
                    "extraction_id": drawing["extraction"].get("timestamp_utc"),
                    "git_sha": drawing["extraction"].get("git_sha")},
        "decisions": {"path": str(decision_snapshot[0]), "sha256": hashlib.sha256(decision_snapshot[1]).hexdigest()}
                     if decision_snapshot else None,
        "previous_run": previous_run,
    }
    combined = {
        "schema_version": "combined-1", "rules_version": "rules-1",
        "created_at": datetime.now(UTC).isoformat(), "case_id": case_id, "inputs": inputs,
        "pairing": {"case_id": case_id, "documents": [report["document"]["id"], drawing["extraction"]["source_path"]],
                    "explanation": "The supplied preprocessing case associates this report and drawing."},
        "candidates": candidates, "matching": matching, **interpretation,
        "brains": {"rules": rules_brain, "llm": llm},
        "decisions_applied": list(applied.values()),
        "decisions_history": decision_history,
    }
    return write_run(combined, case_dir)
