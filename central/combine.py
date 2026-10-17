"""Combine two readings without treating them as independent source evidence."""

from __future__ import annotations

from copy import deepcopy


LEVELS = {"unassessed": 0, "low": 0, "medium": 1, "high": 2, "conflict": -1}


def lower_confidence(rules: str, llm: str) -> str:
    if "conflict" in (rules, llm):
        return "conflict"
    return min((rules, llm), key=lambda value: LEVELS[value])


def _issue_message(issue: dict) -> str:
    for key in ("reason", "explanation", "summary"):
        value = issue.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _issue_key(issue: dict) -> tuple:
    return issue["kind"], tuple(sorted(issue.get("context", []))), _issue_message(issue)


_REPORT_REF_PREFIXES = frozenset({
    "report", "subject", "subjects", "obs", "observation", "evidence", "focus",
    "tumour_focus", "coverage", "coverage_check", "issue",
})
_DRAWING_REF_PREFIXES = frozenset({"drawing", "mark", "standalone", "view", "group", "case"})
_SECTOR_REF_PREFIXES = frozenset({"sector", "redcap"})


def _ref_parts(reference: str) -> tuple[str | None, str]:
    if ":" in reference:
        prefix, value = reference.split(":", 1)
        if value:
            return prefix.lower(), value
    return None, reference


def _touches_reviewed(reference: str, reviewed: set[str], report: set[str],
                      drawing: set[str], other: set[str]) -> bool:
    """Match raw and qualified LLM references without merging two namespaces."""
    if reference in reviewed:
        return True
    prefix, value = _ref_parts(reference)
    if prefix is None:
        return False
    if prefix in _REPORT_REF_PREFIXES:
        return value in report or value in other
    if prefix in _DRAWING_REF_PREFIXES:
        return value in drawing or value in other
    if prefix in _SECTOR_REF_PREFIXES:
        return value in other
    return False


def _confidence(target: dict, opinion: dict) -> None:
    confidence = target.setdefault("confidence", {"final": "low", "explanations": []})
    rules = confidence.get("rules", confidence["final"])
    final = lower_confidence(confidence["final"], lower_confidence(rules, opinion["level"]))
    confidence.update(rules=rules, llm=opinion["level"], final=final)
    confidence.setdefault("explanations", []).append(opinion["reason"])


def combine(interpretation: dict, matching: dict, llm: dict, *, touched: set[str] | None = None) -> tuple[dict, dict]:
    """Return fresh combined structures. Reviewed targets ignore stale LLM opinions."""
    result, matches = deepcopy(interpretation), deepcopy(matching)
    touched = touched or set()
    issues = result.setdefault("issues", [])
    if llm.get("status") != "ok":
        issues.append({"kind": "llm_missing", "severity": "info", "context": [],
                       "reason": llm.get("error", "The LLM brain did not run."),
                       "raised_by": ["llm"], "status": "open"})
        return result, matches

    lesions = {lesion.get("focus") or lesion.get("source_identity") or lesion.get("source_subject") or lesion["id"]:
               lesion for lesion in result["lesions"]}
    rules_assignments = {}
    for hypothesis in matches.get("hypotheses", []):
        rules_assignments[hypothesis["focus"]] = {
            member["subject"] for member in hypothesis.get("memberships", [])
            if member["subject"] != hypothesis["focus"] and not member["subject"].startswith("report:")
        }
    llm_assignments = {item["focus"]: set(item["marks"]) for item in llm.get("assignments", [])}
    reviewed = set(touched)
    reviewed_report: set[str] = set()
    reviewed_drawing: set[str] = set()
    for focus in lesions.keys() | rules_assignments.keys() | llm_assignments.keys():
        lesion = lesions.get(focus)
        report_targets = {focus} if focus else set()
        drawing_targets = rules_assignments.get(focus, set()) | llm_assignments.get(focus, set())
        if lesion:
            drawing_targets.update(lesion.get("marks", []))
        targets = report_targets | drawing_targets
        if lesion:
            targets.add(lesion["id"])
        if targets & touched:
            reviewed.update(targets)
            reviewed_report.update(report_targets)
            reviewed_drawing.update(drawing_targets)
    reviewed_other = reviewed - reviewed_report - reviewed_drawing
    disagreements = set()
    for focus in rules_assignments.keys() | llm_assignments.keys():
        lesion = lesions.get(focus)
        target_ids = {focus, lesion["id"]} if lesion else {focus}
        if target_ids & reviewed or rules_assignments.get(focus, set()) == llm_assignments.get(focus, set()):
            continue
        disagreements.add(focus)
        issues.append({"kind": "matcher_disagreement", "severity": "question", "context": sorted(target_ids),
                       "reason": "Rules and LLM assign different marks to this focus.",
                       "alternatives": [{"brain": "rules", "marks": sorted(rules_assignments.get(focus, set()))},
                                        {"brain": "llm", "marks": sorted(llm_assignments.get(focus, set()))}],
                       "raised_by": ["rules", "llm"], "status": "open"})
        for hypothesis in matches.get("hypotheses", []):
            if hypothesis["focus"] == focus:
                hypothesis["certainty"] = "low"
                for member in hypothesis.get("memberships", []):
                    member["certainty"] = "low"
        if lesion:
            lesion.setdefault("identity_certainty", {}).update(
                level="low", explanation="The two matchers disagree.")

    keyed = {_issue_key(issue): issue for issue in issues}
    for opinion in llm.get("issues", []):
        if any(_touches_reviewed(reference, reviewed, reviewed_report, reviewed_drawing, reviewed_other)
               for reference in opinion.get("context", [])):
            continue
        key = _issue_key(opinion)
        if key in keyed:
            keyed[key]["raised_by"] = sorted(set(keyed[key].get("raised_by", ["rules"])) | {"llm"})
        else:
            issue = {**deepcopy(opinion), "raised_by": ["llm"], "status": "open"}
            issues.append(issue)
            keyed[key] = issue
    for opinion in llm.get("confidence", []):
        lesion = lesions.get(opinion["focus"])
        if not lesion or {opinion["focus"], lesion["id"]} & reviewed:
            continue
        if opinion["property"] in {"sectors", "sector_set"}:
            _confidence(lesion["sectors"], opinion)
        else:
            for prop in lesion.get("properties", []):
                if prop["property"] == opinion["property"]:
                    _confidence(prop, opinion)
    # Assignment disagreement caps the combined result, not the rules-only or LLM reading.
    for focus in disagreements:
        if focus not in lesions:
            continue
        confidence = lesions[focus]["sectors"].setdefault(
            "confidence", {"final": "low", "explanations": []})
        confidence.setdefault("rules", confidence["final"])
        confidence["final"] = lower_confidence(confidence["final"], "low")
        confidence.setdefault("explanations", []).append("The two matchers disagree.")
    return result, matches
