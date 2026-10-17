"""Consistency checks over a report extraction and the combined interpretation.

A check only reports a contradiction. It never changes a status or value, never
promotes an item into another scope, and never treats missing or unassessed
information as a negative finding. Every result is a ``check_failed`` issue with
the rule's source and edition attached.

The caller may pass either the report-3 bundle or its ``extraction`` object.
Reviewer overrides are read from the supplied computation copy, including
``review_decision`` entries; this module does not filter them out.
"""

from __future__ import annotations

import re
from typing import Any

GRADE_RULE = {
    "id": "isup-grade-group",
    "source": "ISUP 2014 consensus (Epstein et al., Am J Surg Pathol 2016;40(2):244-252); "
              "AJCC Cancer Staging Manual 8th ed. grade groups",
    "edition": "ISUP 2014; AJCC 8th",
}
PT2C_RULE = {
    "id": "pt2c-both-lobes",
    "source": "AJCC Cancer Staging Manual 7th ed., prostate pT2c (tumour involves both lobes); "
              "AJCC 8th ed. removed pT2 substages",
    "edition": "AJCC 7th; REDCap project 64 retains pT2a/b/c choices",
}
PT2AB_RULE = {
    "id": "pt2ab-one-lobe",
    "source": "AJCC Cancer Staging Manual 7th ed., prostate pT2a and pT2b (one lobe); "
              "AJCC 8th ed. removed pT2 substages",
    "edition": "AJCC 7th; REDCap project 64 retains pT2a/b/c choices",
}
PT3A_RULE = {
    "id": "pt3a-epe",
    "source": "AJCC Cancer Staging Manual 8th ed., prostate pT3a (extraprostatic extension)",
    "edition": "AJCC 8th",
}
PT3B_RULE = {
    "id": "pt3b-seminal-vesicles",
    "source": "AJCC Cancer Staging Manual 8th ed., prostate pT3b (seminal vesicle invasion)",
    "edition": "AJCC 8th",
}

_LOCATION_KEYS = ("sides", "patient_sides", "side", "laterality", "sectors", "sectors_in", "sectors_maybe")


def _extraction(report: Any) -> dict:
    if isinstance(report, dict) and isinstance(report.get("extraction"), dict):
        return report["extraction"]
    return report if isinstance(report, dict) else {}


def _subjects(extraction: dict) -> list[dict]:
    subjects = extraction.get("subjects", [])
    return [item for item in subjects if isinstance(item, dict)] if isinstance(subjects, list) else []


def _observations(extraction: dict) -> list[dict]:
    observations = extraction.get("observations", [])
    return [item for item in observations if isinstance(item, dict)] if isinstance(observations, list) else []


def _observations_for(extraction: dict, subject_id: str | None, property_name: str) -> list[dict]:
    if not subject_id:
        return []
    return [item for item in _observations(extraction)
            if item.get("subject_id") == subject_id and item.get("property") == property_name]


def _recorded(extraction: dict, subject_id: str | None, property_name: str) -> dict | None:
    from .matching import observed
    return observed({"extraction": {"observations": _observations(extraction)}}, subject_id, property_name)


def _presence(observation: dict | None) -> str | None:
    if not observation or observation.get("status") != "recorded":
        return None
    value = observation.get("value")
    if not isinstance(value, dict) or value.get("type") != "presence":
        return None
    result = value.get("value")
    return result if result in {"present", "absent", "indeterminate"} else None


def _pattern(*candidates: Any) -> int | None:
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = candidate.get("pattern")
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, int) and 1 <= candidate <= 5:
            return candidate
    return None


def _gleason_patterns(observation: dict | None) -> tuple[int | None, int | None, int] | None:
    if not observation or observation.get("status") != "recorded":
        return None
    value = observation.get("value")
    if not isinstance(value, dict):
        return None
    primary = _pattern(value.get("primary"), value.get("primary_pattern"))
    secondary = _pattern(value.get("secondary"), value.get("secondary_pattern"))
    if primary is None or secondary is None:
        total = value.get("total")
        if value.get("type") == "gleason_score" and type(total) is int and 2 <= total <= 10:
            return None, None, total
        return None
    return primary, secondary, primary + secondary


def _grade_group(observation: dict | None) -> int | None:
    if not observation or observation.get("status") != "recorded":
        return None
    value = observation.get("value")
    if not isinstance(value, dict):
        return None
    code = value.get("code")
    if code is None:
        code = value.get("value")
    if isinstance(code, bool):
        return None
    if isinstance(code, int) and 1 <= code <= 5:
        return code
    if isinstance(code, str):
        match = re.fullmatch(r"\s*(?:gg|g|grade\s*group)?\s*([1-5])\s*", code, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _grade_group_from_gleason(patterns: tuple[int | None, int | None, int]) -> int | None:
    primary, secondary, total = patterns
    if total <= 6:
        return 1
    if total == 7:
        if (primary, secondary) == (3, 4):
            return 2
        if (primary, secondary) == (4, 3):
            return 3
        return None
    if total == 8:
        return 4
    if total >= 9:
        return 5
    return None


def _gleason_for(extraction: dict, subject_id: str) -> tuple[tuple[int | None, int | None, int] | None, dict | None]:
    patterns_observation = _recorded(extraction, subject_id, "gleason_patterns")
    patterns = _gleason_patterns(patterns_observation)
    if patterns is not None:
        return patterns, patterns_observation
    score_observation = _recorded(extraction, subject_id, "gleason_score")
    patterns = _gleason_patterns(score_observation)
    return patterns, score_observation


def _context(*values: Any) -> list[str]:
    result = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _issue(rule: dict, severity: str, context: list[str], reason: str) -> dict:
    return {
        "kind": "check_failed",
        "severity": severity,
        "context": _context(*context),
        "reason": reason,
        "rule": dict(rule),
    }


def _grade_issues(extraction: dict, subjects: list[dict]) -> list[dict]:
    result = []
    for subject in subjects:
        kind = subject.get("kind")
        if kind not in {"tumour_focus", "specimen"}:
            continue
        subject_id = subject.get("id")
        if not isinstance(subject_id, str):
            continue
        grade_observation = _recorded(extraction, subject_id, "grade_group")
        reported = _grade_group(grade_observation)
        patterns, patterns_observation = _gleason_for(extraction, subject_id)
        if patterns is None:
            continue
        expected = _grade_group_from_gleason(patterns)
        if reported is None or expected is None or reported == expected:
            continue
        primary, secondary, total = patterns
        scope = "Focus" if kind == "tumour_focus" else "Specimen"
        score_description = (f"{primary}+{secondary}={total}" if primary is not None and secondary is not None
                             else f"total {total} without stated component patterns")
        result.append(_issue(
            GRADE_RULE, "question",
            _context(subject_id, patterns_observation.get("id") if patterns_observation else None,
                     grade_observation.get("id") if grade_observation else None),
            f"{scope} {subject_id!r} reports grade group {reported} but Gleason "
            f"{score_description} maps to grade group {expected} under ISUP 2014.",
        ))
    return result


def _code(value: dict) -> str | None:
    for key in ("original_code", "normalized_code", "code"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _pt(extraction: dict, specimen_id: str | None) -> tuple[int, str | None, dict | None]:
    observation = _recorded(extraction, specimen_id, "classification_pt")
    if not observation:
        return 0, None, None
    value = observation.get("value")
    if not isinstance(value, dict):
        return 0, None, None
    code = _code(value)
    if code is None:
        return 0, None, observation
    normalized = re.sub(r"\s+", "", code).upper().strip(".;,")
    match = re.fullmatch(r"P?T?([0-4])([ABC])?", normalized)
    if not match:
        return 0, None, observation
    category = match.group(2)
    return int(match.group(1)), category.lower() if category else None, observation


def _side_tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        if "laterality" in value:
            value = value.get("laterality")
        elif value.get("type") == "location":
            value = None
        else:
            value = value.get("value")
    if isinstance(value, str):
        lowered = value.lower()
        if "bilateral" in lowered:
            return {"right", "left"}
        if lowered in {"r", "right", "pravý", "prava", "vpravo"}:
            return {"right"}
        if lowered in {"l", "left", "levý", "leva", "vlevo"}:
            return {"left"}
        return set(re.findall(r"\b(right|left)\b", lowered))
    if isinstance(value, (list, tuple, set)):
        result = set()
        for item in value:
            result.update(_side_tokens(item))
        return result
    return set()


def _sector_sides(value: Any) -> set[str]:
    result = set()
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict):
            result.update(_side_tokens(item.get("patient_side") or item.get("side")))
            code = item.get("redcap")
        else:
            code = item
        if isinstance(code, str):
            if code.endswith("_rs"):
                result.add("right")
            elif code.endswith("_ls"):
                result.add("left")
    return result


def _item_sides(item: dict) -> set[str]:
    result = set()
    for key in ("sides", "patient_sides", "side", "laterality"):
        if key in item:
            result.update(_side_tokens(item[key]))
    sectors = item.get("sectors")
    if isinstance(sectors, dict):
        result.update(_sector_sides(sectors.get("in", [])))
    elif isinstance(sectors, list):
        result.update(_sector_sides(sectors))
    if "sectors_in" in item:
        result.update(_sector_sides(item["sectors_in"]))
    properties = item.get("properties")
    if isinstance(properties, list):
        for prop in properties:
            if not isinstance(prop, dict) or prop.get("property") not in {"laterality", "side"}:
                continue
            if prop.get("status") not in {None, "recorded"}:
                continue
            result.update(_side_tokens(prop.get("value")))
    return result


def _mentions_location(item: dict) -> bool:
    if any(key in item for key in _LOCATION_KEYS):
        return True
    properties = item.get("properties")
    return isinstance(properties, list) and any(
        isinstance(prop, dict) and prop.get("property") in {"laterality", "side"} for prop in properties)


def _one_sided(items: list[dict]) -> tuple[str | None, list[str]]:
    """Return the single side and the IDs that make it one-sided, or no conclusion."""
    known: set[str] = set()
    ids: list[str] = []
    located = False
    for item in items:
        if not isinstance(item, dict) or not _mentions_location(item):
            continue
        located = True
        sides = _item_sides(item)
        if not sides:
            return None, []
        known.update(sides)
        ident = item.get("id")
        if isinstance(ident, str):
            ids.append(ident)
    if not located or known not in ({"right"}, {"left"}):
        return None, []
    return next(iter(known)), ids


def _both_sided(lesions: list[dict]) -> bool:
    known: set[str] = set()
    located = False
    for item in lesions:
        if not isinstance(item, dict) or not _mentions_location(item):
            continue
        located = True
        sides = _item_sides(item)
        if not sides:
            return False
        known.update(sides)
    return located and {"right", "left"} <= known


def _pt_issues(extraction: dict, specimen: dict | None, lesions: list[dict],
               candidates: list[dict]) -> list[dict]:
    specimen_id = specimen.get("id") if specimen else None
    group, category, observation = _pt(extraction, specimen_id)
    observation_id = observation.get("id") if observation else None
    result = []

    if group == 2 and category == "c":
        side, ids = _one_sided([*lesions, *candidates])
        if side:
            result.append(_issue(
                PT2C_RULE, "info", _context(specimen_id, observation_id, *ids),
                f"pT2c means both lobes, but every lesion and drawing candidate with a known "
                f"side is on the {side}.",
            ))

    if group == 2 and category in {"a", "b"}:
        if _both_sided(lesions):
            result.append(_issue(
                PT2AB_RULE, "info", _context(specimen_id, observation_id,
                                              *[item.get("id") for item in lesions]),
                f"pT2{category} means one lobe, but lesions are recorded on both right and left.",
            ))

    if group == 3 and category == "a":
        foci = [subject for subject in _subjects(extraction) if subject.get("kind") == "tumour_focus"]
        present = False
        unknown = not foci
        absent_ids: list[str] = []
        focus_ids: list[str] = []
        for focus in foci:
            focus_id = focus.get("id")
            if isinstance(focus_id, str):
                focus_ids.append(focus_id)
            observations = _observations_for(extraction, focus_id, "extraprostatic_extension")
            if not observations:
                unknown = True
                continue
            for item in observations:
                value = _presence(item)
                if value == "present":
                    present = True
                elif value == "absent" and item.get("status") == "recorded":
                    if isinstance(item.get("id"), str):
                        absent_ids.append(item["id"])
                else:
                    unknown = True
        if not present and not unknown:
            result.append(_issue(
                PT3A_RULE, "info", _context(specimen_id, observation_id, *focus_ids, *absent_ids),
                "pT3a requires extraprostatic extension in at least one focus, but every focus "
                "with a recorded value says absent.",
            ))

    if group == 3 and category == "b":
        observations = _observations_for(extraction, specimen_id, "seminal_vesicle_invasion")
        present = False
        unknown = not observations
        absent: list[str] = []
        for item in observations:
            value = _presence(item)
            if value == "present":
                present = True
            elif value == "absent" and item.get("status") == "recorded":
                if isinstance(item.get("id"), str):
                    absent.append(item["id"])
            else:
                unknown = True
        if not present and not unknown:
            result.append(_issue(
                PT3B_RULE, "info", _context(specimen_id, observation_id, *absent),
                "pT3b requires seminal vesicle invasion, but the specimen records it as absent.",
            ))

    return result


def run_checks(report: dict, lesions: list[dict], candidates: list[dict]) -> list[dict]:
    """Return ``check_failed`` issues for the supplied computation copy.

    Grade group is checked per focus and separately at specimen scope. pT2c
    uses lesions and candidates; pT2a/b uses lesions only. pT3a uses focus-level
    extraprostatic extension; pT3b uses the specimen's seminal vesicle finding.
    """
    extraction = _extraction(report)
    subjects = _subjects(extraction)
    specimen = next((subject for subject in subjects if subject.get("kind") == "specimen"), None)
    lesions = [item for item in (lesions or []) if isinstance(item, dict)]
    candidates = [item for item in (candidates or []) if isinstance(item, dict)]
    return [
        *_grade_issues(extraction, subjects),
        *_pt_issues(extraction, specimen, lesions, candidates),
    ]
