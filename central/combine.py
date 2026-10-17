"""Combine two readings without treating them as independent source evidence."""

from __future__ import annotations

from copy import deepcopy


LEVELS = {"unassessed": 0, "low": 0, "medium": 1, "high": 2, "conflict": -1}


def lower_confidence(rules: str, llm: str) -> str:
    if "conflict" in (rules, llm):
        return "conflict"
    return min((rules, llm), key=lambda value: LEVELS[value])


def _issue_key(issue: dict) -> tuple:
    return issue["kind"], tuple(sorted(issue.get("context", [])))


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

    lesions = {lesion.get("focus", lesion.get("source_subject")): lesion for lesion in result["lesions"]}
    rules_assignments = {}
    for hypothesis in matches.get("hypotheses", []):
        rules_assignments[hypothesis["focus"]] = {
            member["subject"] for member in hypothesis.get("memberships", [])
            if member["subject"] != hypothesis["focus"] and not member["subject"].startswith("report:")
        }
    llm_assignments = {item["focus"]: set(item["marks"]) for item in llm.get("assignments", [])}
    reviewed = set(touched)
    for focus in lesions.keys() | rules_assignments.keys() | llm_assignments.keys():
        lesion = lesions.get(focus)
        targets = {focus} | rules_assignments.get(focus, set()) | llm_assignments.get(focus, set())
        if lesion:
            targets.update({lesion["id"], *lesion.get("marks", [])})
        if targets & touched:
            reviewed.update(targets)
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
        if set(opinion.get("context", [])) & reviewed:
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
