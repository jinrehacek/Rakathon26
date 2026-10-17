"""Reviewable interpretations from text subjects and a supplied matching result."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .candidates import crosswalk_rows
from .confidence import confidence, sector_confidence, text_confidence
from .issues import (candidate_signals, filter_signals, issue, number_issues,
                     size_note_issues)
from .matching import location, observations, observed, subjects, sides_compatible
from .rules import ZONE_TABLE


def property_assessments(report: dict, subject_id: str) -> list[dict]:
    result = []
    for obs in observations(report, subject_id):
        assessment = {
            "property": obs["property"], "status": obs["status"], "basis": obs["basis"],
            "disposition": "adopted" if obs["status"] == "recorded" else
                           "not applicable" if obs["status"] == "not applicable" else "unavailable",
            "supports": ["report:" + obs["id"]], "opposes": [], "tags": ["single source"],
            "evidence_ids": ["report:" + evidence for evidence in obs.get("evidence_ids", [])],
            "derived_from": ["report:" + source for source in obs.get("derived_from", [])],
            "confidence": text_confidence(obs), "source_certainty": deepcopy(obs.get("certainty", {})),
            "review_status": "unreviewed",
            "rationale": "Retained source observation at its original subject scope.",
        }
        if obs["status"] == "recorded":
            assessment["value"] = deepcopy(obs["value"])
        if obs.get("unavailable_reason"):
            assessment["unavailable_reason"] = obs["unavailable_reason"]
        result.append(assessment)
    return result


def text_sectors(report: dict, focus_id: str, rows: list[dict]) -> list[str]:
    loc = location(report, focus_id)
    if not all(loc[prop] for prop in ("laterality", "level", "zone")):
        return []
    return sorted(row["redcap_code"] for row in rows
                  if row["patient_side"] in loc["laterality"] and row["level"] in loc["level"]
                  and ZONE_TABLE.get(row["zone"], (None, None))[0] in loc["zone"])


def build_interpretation(report: dict, drawing: dict, candidates: list[dict], matching: dict,
                         crosswalk_path: Path | None = None) -> dict:
    """Never search or change supplied assignments; source focus IDs remain raw."""
    rows = crosswalk_rows(crosswalk_path)
    index = {candidate["id"]: candidate for candidate in candidates}
    foci = subjects(report, "tumour_focus")
    # Python's stable sort preserves report order within each dominance class.
    foci.sort(key=lambda focus: (observed(report, focus["id"], "dominant") or {}).get("value", {}).get("value") != "present")
    hypotheses = {hypothesis["focus"]: hypothesis for hypothesis in matching.get("hypotheses", [])}
    assignments = matching["best_assignment"]
    issues, lesions, other_findings = [], [], []
    used = {cid for ids in assignments.values() for cid in ids}

    # Explain non-tumour leftovers first, including before drawing-backed fallback.
    for number, finding in enumerate(subjects(report, "other_finding"), 1):
        loc = location(report, finding["id"])
        ids = [candidate["id"] for candidate in candidates if candidate["id"] not in used
               and loc["laterality"] and loc["level"]
               and sides_compatible(loc["laterality"], set(candidate["sides"]))
               and loc["level"] & set(candidate["levels"])]
        used.update(ids)
        other_findings.append({"id": f"O{number}", "kind": "other finding", "focus": finding["id"],
                               "source_subject": "report:" + finding["id"], "candidates": ids,
                               "marks": [mark for cid in ids for mark in index[cid]["marks"]],
                               "properties": property_assessments(report, finding["id"]),
                               "review_status": "unreviewed", "export_disposition": "deferred",
                               "rationale": "Report non-tumour finding; leftover candidate location is compatible."})

    for focus in foci:
        fid = focus["id"]
        chosen = [index[cid] for cid in assignments.get(fid, [])]
        hid = hypotheses.get(fid)
        lesion = {
            "id": f"L{len(lesions) + 1}", "order": len(lesions) + 1, "kind": "tumour focus",
            "focus": fid, "candidates": [candidate["id"] for candidate in chosen],
            "marks": [mark for candidate in chosen for mark in candidate["marks"]],
            "properties": property_assessments(report, fid), "review_status": "unreviewed",
            "identity_disposition": "provisional" if chosen else "adopted",
            "supports": ["report:" + obs["id"] for obs in observations(report, fid)],
            "rationale": "One report focus remains one lesion, with matching conditions retained.",
        }
        if chosen:
            if not hid:
                raise ValueError(f"assignment for {fid} has no materialized hypothesis")
            lesion["hypothesis"] = hid["id"]
        else:
            lesion["source_subject"] = "report:" + fid
        loc = location(report, fid)
        sides = {side for candidate in chosen for side in candidate["sides"]}
        levels = {level for candidate in chosen for level in candidate["levels"]}
        aps = {ap for candidate in chosen for ap in candidate["anteroposterior"]}
        zones = {zone for candidate in chosen for zone in candidate["zones"]}
        side_conflict = bool(loc["laterality"] and sides and not sides_compatible(loc["laterality"], sides))
        ap_conflict = bool(loc["anteroposterior"] and aps and not loc["anteroposterior"] & aps)
        zone_conflict = bool(loc["zone"] and zones and not loc["zone"] & zones)
        lesion["side_agrees"] = bool(loc["laterality"] and sides and not side_conflict)
        lesion["level_agrees"] = bool(loc["level"] and levels and not loc["level"] - levels)
        for prop, conflict, kind in (("laterality", side_conflict, "side_conflict"),
                                      ("anteroposterior", ap_conflict, "ap_conflict"),
                                      ("zone", zone_conflict, "other"),
                                      ("level", bool(chosen and loc["level"] and levels and loc["level"] - levels), "level_conflict")):
            if not conflict:
                continue
            obs = observed(report, fid, prop)
            issues.append(issue(kind, "question", [lesion["id"], "report:" + obs["id"]] + lesion["marks"],
                                f"Report and drawing {prop} disagree; review both source values."))
            for assessment in lesion["properties"]:
                if assessment["property"] == prop:
                    value = assessment.pop("value")
                    drawing_value = {"type": "location", {"laterality": "laterality", "level": "levels", "zone": "zones", "anteroposterior": "anteroposterior"}[prop]:
                                     sorted(sides if prop == "laterality" else levels if prop == "level" else zones if prop == "zone" else aps)}
                    if prop not in {"level", "zone"}:
                        drawing_value[prop] = ("bilateral" if prop == "laterality" and len(sides) > 1 else
                                               next(iter(sides if prop == "laterality" else aps)))
                    assessment.update(disposition="unresolved", candidates=[
                        {"value": value, "supports": assessment["supports"], "basis": assessment["basis"]},
                        {"value": drawing_value, "supports": lesion["marks"], "basis": "inferred"}],
                        opposes=lesion["marks"], rationale="Conflicting source values remain unresolved.",
                        confidence=confidence("conflict" if prop not in {"level", "zone"} else "low",
                                              "Report and drawing location disagree; no combined value is selected."))
        if chosen:
            inside = sorted({code for candidate in chosen for code in candidate["sectors_in"]})
            maybe = sorted({code for candidate in chosen for code in candidate["sectors_maybe"]} - set(inside))
        else:
            inside, maybe = text_sectors(report, fid, rows), []
            issues.append(issue("unmatched_focus", "question", [lesion["id"], "report:" + fid],
                                "The reported focus has no drawing candidate."))
            if inside:
                issues.append(issue("inferred_sectors", "question", [lesion["id"]] + lesion["supports"],
                                    "Review sectors inferred from report side, level and zone."))
        identity_certainty = hid.get("certainty", matching["certainty"]) if hid else matching["certainty"]
        lesion["identity_certainty"] = {"level": identity_certainty, "explanation": "Retained per-focus matching certainty."}
        lesion["sectors"] = {"in": inside, "maybe": maybe, "basis": "inferred",
                             "status": "recorded" if inside else "not assessed",
                             "disposition": "provisional" if inside else "unavailable",
                             "supports": lesion["marks"] if chosen else ["report:" + obs["id"] for obs in observations(report, fid)
                                                                            if obs["property"] in {"laterality", "level", "zone"}],
                             "opposes": [], "review_status": "unreviewed",
                             "confidence": sector_confidence(identity_certainty, lesion["side_agrees"],
                                                             bool(chosen) and all(c["side_basis"] == "explicit" for c in chosen),
                                                             candidate_signals(drawing, chosen),
                                                             side_conflict or ap_conflict, not chosen)}
        if zone_conflict and lesion["sectors"]["confidence"]["final"] != "conflict":
            lesion["sectors"]["confidence"] = confidence("low", "Report and drawing zones disagree; review both readings before selecting sectors.")
        lesions.append(lesion)

    specimen_subject = subjects(report, "specimen")[0]
    specimen_id = specimen_subject["id"]
    count_obs = observed(report, specimen_id, "reported_lesion_count")
    multifocal = observed(report, specimen_id, "multifocality")
    fallback_support = ["report:" + obs["id"] for obs in (count_obs, multifocal) if obs and
                        ((obs["property"] == "reported_lesion_count" and obs["value"].get("value", 0) > 0)
                         or obs["value"].get("code") == "multifocal")]
    if not foci and fallback_support and not (count_obs and count_obs["value"]["value"] == 0):
        for candidate in candidates:
            if candidate["id"] in used:
                continue
            lesion_id = f"L{len(lesions) + 1}"
            lesions.append({"id": lesion_id, "order": len(lesions) + 1, "kind": "tumour focus",
                            "focus": None, "source_subject": candidate["marks"][0],
                            "candidates": [candidate["id"]], "marks": list(candidate["marks"]),
                            "properties": [], "identity_disposition": "provisional", "review_status": "unreviewed",
                            "basis": "inferred", "supports": fallback_support + candidate["marks"],
                            "depends_on": candidate.get("depends_on", []),
                            "rationale": "Drawing-backed provisional lesion supported by the specimen count or multifocality statement.",
                            "identity_certainty": {"level": "low", "explanation": "No individual report focus establishes this candidate's identity."},
                            "sectors": {"in": list(candidate["sectors_in"]), "maybe": list(candidate["sectors_maybe"]),
                                        "basis": "inferred", "status": "recorded" if candidate["sectors_in"] else "not assessed",
                                        "disposition": "provisional" if candidate["sectors_in"] else "unavailable",
                                        "supports": candidate["marks"], "opposes": [], "review_status": "unreviewed",
                                        "confidence": sector_confidence("low", False, False, [])}})
            used.add(candidate["id"])
            issues.append(issue("lesion_from_drawing", "question", [lesion_id] + fallback_support + candidate["marks"],
                                "Confirm this provisional lesion inferred from drawing and the specimen statement."))
    for candidate in candidates:
        if candidate["id"] not in used:
            issues.append(issue("unmatched_candidate", "question", [candidate["id"]] + candidate["marks"],
                                "Drawing ink has no compatible report focus or other finding; it does not create a lesion."))
    if count_obs and count_obs["value"]["value"] != len(lesions):
        issues.append(issue("count_mismatch", "question", ["report:" + count_obs["id"]] + [lesion["id"] for lesion in lesions],
                            f"Report count {count_obs['value']['value']} differs from {len(lesions)} interpreted lesions."))
    if matching.get("certainty") == "low" and not matching.get("fixed_assignment") and foci:
        issues.append(issue("ambiguous_assignment", "question", [hyp["id"] for hyp in matching["hypotheses"]],
                            "The best and runner-up assignments differ by less than one point.",
                            alternatives=[matching["best_assignment"], matching.get("runner_up_assignment")],
                            preselected=matching["best_assignment"]))
    signals, details = filter_signals(drawing, lesions, candidates, rows)
    issues.extend(signals)
    issues.extend(size_note_issues(report, drawing, lesions, details))
    for extraction_issue in report["extraction"].get("issues", []):
        issues.append(issue(extraction_issue["kind"], "question",
                            ["report:" + extraction_issue["id"]] + ["report:" + sid for sid in extraction_issue.get("alternative_subject_ids", [])],
                            extraction_issue["summary"], source_issue=deepcopy(extraction_issue)))
    return {"lesions": lesions,
            "specimen": {"kind": "specimen", "source_subject": "report:" + specimen_id,
                         "properties": property_assessments(report, specimen_id)},
            "other_findings": other_findings, "issues": number_issues(issues), "details": details}
