"""Exhaustive assignment and fixed-assignment materialization for decision reruns."""
from __future__ import annotations

from itertools import combinations

from .confidence import matching_confidence
from .rules import (EXTRA_STANDALONE_PENALTY, HIGH_MARGIN, LEVEL_AGREE,
                    LEVEL_MISSING, LOCATION_AGREE, LOCATION_CONFLICT, SIDE_AGREE,
                    SIDE_CONFLICT, SIZE_RANK_BONUS, RULES_VERSION)

LOCATION_PROPERTIES = (("laterality", "sides"), ("level", "levels"),
                       ("zone", "zones"), ("anteroposterior", "anteroposterior"))
PROPERTY_LABELS = {"laterality": "laterality", "level": "level", "zone": "zone",
                   "anteroposterior": "anteroposterior position"}


def subjects(report: dict, kind: str) -> list[dict]:
    return [subject for subject in report["extraction"]["subjects"] if subject["kind"] == kind]


def observations(report: dict, subject_id: str) -> list[dict]:
    return [obs for obs in report["extraction"]["observations"] if obs["subject_id"] == subject_id]


def observed(report: dict, subject_id: str, prop: str) -> dict | None:
    matches = [obs for obs in observations(report, subject_id) if obs["property"] == prop]
    # A reviewed computation copy can contain repeated, identical overrides.
    if len(matches) > 1 and not all(o.get("review_decision") and o.get("value") == matches[0].get("value") for o in matches):
        return None
    return next((obs for obs in matches if obs["status"] == "recorded"), None)


def property_observation(report: dict, subject_id: str, prop: str) -> dict | None:
    """Keep the raw unavailable observation when no recorded value exists."""
    matches = [obs for obs in observations(report, subject_id) if obs["property"] == prop]
    return observed(report, subject_id, prop) if len(matches) > 1 else (matches[0] if matches else None)


def location(report: dict, subject_id: str) -> dict[str, set[str]]:
    result = {}
    for prop, key in (("laterality", "laterality"), ("level", "levels"), ("zone", "zones"),
                      ("anteroposterior", "anteroposterior")):
        obs = observed(report, subject_id, prop)
        value = obs["value"].get(key) if obs else None
        values = set(value if isinstance(value, list) else [value] if value else [])
        if prop == "laterality" and "bilateral" in values:
            values = {"right", "left"}
        result[prop] = values
    if not result["anteroposterior"] and result["zone"]:
        from .rules import ZONE_TABLE
        result["anteroposterior"] = {ZONE_TABLE[z][1] for z in result["zone"] if z in ZONE_TABLE and ZONE_TABLE[z][1]}
    return result


def zones_overlap(text: set[str], exact: set[str], broad: set[str]) -> bool:
    from .rules import ZONE_TABLE
    if exact:
        return any(z == candidate or z == ZONE_TABLE.get(candidate, (None, None))[0]
                   for z in text for candidate in exact)
    return bool(text & broad)


def dimensions_mm(obs: dict | None) -> list[float]:
    if not obs:
        return []
    factors = {"mm": 1, "cm": 10}
    return [measurement["value"] * factors[measurement["unit"]]
            for measurement in obs["value"].get("measurements", [])
            if measurement["unit"] in factors]


def sides_compatible(report_sides: set[str], drawing_sides: set[str]) -> bool:
    """A drawing may depict part of a bilateral focus, but cannot add an opposite lobe."""
    return bool(report_sides and drawing_sides and drawing_sides <= report_sides)


def _values(items) -> str:
    return ", ".join(sorted(items)) if items else "none"


def _report_input(obs: dict | None) -> dict | None:
    if not obs:
        return None
    result = {"ref": "report:" + obs["id"], "status": obs["status"], "basis": obs["basis"]}
    if obs.get("unavailable_reason"):
        result["unavailable_reason"] = obs["unavailable_reason"]
    return result


def _orientation_assumptions(candidate: dict) -> list[str]:
    if candidate.get("side_basis") == "explicit":
        return ["Treats drawing sides as patient sides from explicit P/L orientation on the contributing views."]
    return ["Treats drawing sides as patient-side interpretations inferred from view orientation.",
            "The report side is not used to assign the drawing side, so side agreement is not independent corroboration."]


def _comparison_assumptions(prop: str, candidate: dict, outcome: str, drawing_known: bool) -> list[str]:
    if prop == "laterality":
        assumptions = _orientation_assumptions(candidate)
    elif prop == "level":
        assumptions = ["Treats axial sector levels and longitudinal band levels as the same base/mid/apex scale."]
    elif prop == "zone":
        assumptions = ["Maps drawing sectors to zones with the rules-1 zone table; compares anatomical zone, not pixel position."]
    else:
        assumptions = ["Maps drawing sectors to anterior/posterior through the rules-1 zone table."]
    if outcome == "no counterpart":
        assumptions.append("Relies on the report coverage check for this property; an unavailable status is not an explicit negative.")
    elif outcome == "indeterminate":
        assumptions.append("Treats unresolved report or drawing knowledge as indeterminate, not as an absent finding.")
        if prop == "laterality":
            assumptions.append("Requires supported patient-side orientation before laterality can be compared.")
    elif outcome == "conflict":
        assumptions.append("Keeps both source values; the score does not choose a winning side, level, zone or position.")
    if not drawing_known and prop == "laterality":
        assumptions.append("No supported drawing side was available; image side is not substituted for patient side.")
    return list(dict.fromkeys(assumptions))


def _independence_limitation(prop: str, candidate: dict) -> str:
    if prop == "laterality":
        if candidate.get("side_basis") == "explicit":
            return "Drawing side rests on explicit P/L orientation, but agreement with report text still does not establish identity."
        return "Drawing side rests on inferred orientation and cannot independently confirm report laterality."
    if prop == "level":
        return "Drawing level comes from sector or band interpretation; agreement does not establish identity."
    return "Drawing location comes from sector interpretation; agreement does not establish identity."


def pair_score(report: dict, focus: dict, candidate: dict, size_bonus: bool = False) -> tuple[float, list[dict]]:
    loc = location(report, focus["id"])
    comparisons = []
    total = 0.0
    for prop, field in LOCATION_PROPERTIES:
        obs = property_observation(report, focus["id"], prop)
        report_input = _report_input(obs)
        text, drawing = loc[prop], set(candidate.get("exact_zones", candidate.get(field, [])) if prop == "zone" else candidate.get(field, []))
        label = PROPERTY_LABELS[prop]
        if obs is not None and obs["status"] != "recorded" and not text:
            score, outcome, review_status = 0.0, "no counterpart", "unreviewed"
            reason = f" ({obs['unavailable_reason']})" if obs.get("unavailable_reason") else ""
            if drawing:
                explanation = (f"Report {label} has status '{obs['status']}'{reason}; no recorded text value exists, "
                               f"so the drawing value ({_values(drawing)}) has no counterpart. This is not an explicit negative.")
            else:
                explanation = (f"Report {label} has status '{obs['status']}'{reason}; no recorded text value exists, "
                               f"and the candidate supplies no {label} evidence, so there is no counterpart on either side.")
        elif not text:
            score, outcome, review_status = 0.0, "indeterminate", "needs_review"
            if obs is None:
                explanation = (f"No report {label} observation exists, so {prop} is not compared; "
                               "a missing observation is not a checked omission.")
            else:
                explanation = (f"Report {label} is recorded but has no usable value, so {prop} remains indeterminate; "
                               "no conclusion is drawn.")
        elif not drawing:
            score, outcome, review_status = 0.0, "indeterminate", "needs_review"
            orientation = " or supported patient-side orientation" if prop == "laterality" else ""
            explanation = (f"The drawing candidate supplies no {label} evidence{orientation}, so {prop} cannot be compared; "
                           "absent drawing knowledge is indeterminate, not no counterpart.")
        elif prop == "level":
            shared, missing = text & drawing, text - drawing
            score = LEVEL_AGREE * len(shared) + LEVEL_MISSING * len(missing)
            outcome = "conflict" if missing else "agreement"
            review_status = "needs_review" if missing else "unreviewed"
            details = f"{len(shared)} shared level(s) ({_values(shared)}) contribute {LEVEL_AGREE * len(shared):+.1f}"
            if missing:
                explanation = (f"{details}; {len(missing)} report level(s) absent from the drawing "
                               f"({_values(missing)}) subtract {abs(LEVEL_MISSING) * len(missing):.1f}. Both levels remain for review.")
            else:
                explanation = f"{details}. The drawing covers every reported level."
        elif prop == "laterality":
            agrees = sides_compatible(text, drawing)
            score = SIDE_AGREE if agrees else SIDE_CONFLICT
            outcome = "agreement" if agrees else "conflict"
            review_status = "unreviewed" if agrees else "needs_review"
            if agrees:
                explanation = f"Report side {_values(text)} overlaps drawing side {_values(drawing)} for {score:+.1f}."
                if candidate.get("side_basis") != "explicit":
                    explanation += " The drawing side comes from inferred orientation, so this is not independent confirmation."
            else:
                explanation = (f"Report side {_values(text)} conflicts with drawing side {_values(drawing)} for {score:+.1f}; "
                               "both sides remain available for review.")
        else:
            agrees = zones_overlap(text, set(candidate.get("exact_zones", [])), drawing) if prop == "zone" else bool(text & drawing)
            score = LOCATION_AGREE if agrees else LOCATION_CONFLICT
            outcome = "agreement" if agrees else "conflict"
            review_status = "unreviewed" if agrees else "needs_review"
            if agrees:
                explanation = f"Report {label} {_values(text)} overlaps drawing {label} {_values(drawing)} for {score:+.1f}."
            else:
                explanation = (f"Report {label} {_values(text)} conflicts with drawing {label} {_values(drawing)} for {score:+.1f}; "
                               "both values remain for review.")
        total += score
        comparisons.append({
            "property": prop, "candidate": candidate["id"], "score": score,
            "inputs": ["report:" + o["id"] for o in observations(report, focus["id"]) if o["property"] == prop] + candidate["marks"],
            "report_ref": report_input["ref"] if report_input else None,
            "report_status": obs["status"] if obs else None,
            "input_observations": [report_input] if report_input else [],
            "text": sorted(text), "drawing": sorted(drawing), "outcome": outcome,
            "rule": f"{RULES_VERSION}/{prop}",
            "explanation": explanation,
            "review_status": review_status,
            "assumptions": _comparison_assumptions(prop, candidate, outcome, bool(drawing)),
            "independence_limitation": _independence_limitation(prop, candidate),
        })
    dimensions_input = _report_input(property_observation(report, focus["id"], "dimensions"))
    if size_bonus:
        total += SIZE_RANK_BONUS
        size_explanation = (f"The largest text dimension and highest sector count coincide, adding {SIZE_RANK_BONUS:+.1f}; "
                            "this is a rank tie-break, not physical size agreement.")
    else:
        size_explanation = ("No size-rank bonus applies because this pair is not the largest-text/highest-sector-count "
                            "combination; sector counts and pixels are not millimetres.")
    comparisons.append({
        "property": "size_rank", "candidate": candidate["id"],
        "score": SIZE_RANK_BONUS if size_bonus else 0.0,
        "outcome": "not comparable",
        "inputs": ([dimensions_input["ref"]] if dimensions_input else []) + candidate["marks"],
        "report_ref": dimensions_input["ref"] if dimensions_input else None,
        "report_status": dimensions_input["status"] if dimensions_input else None,
        "input_observations": [dimensions_input] if dimensions_input else [],
        "rule": f"{RULES_VERSION}/size_rank",
        "explanation": size_explanation,
        "review_status": "unreviewed",
        "assumptions": [
            "Treats the largest recorded text dimension and highest in-sector count as comparable rank proxies.",
            "Does not convert schematic pixels or sector area into millimetres.",
        ],
    })
    return total, comparisons


def _score_terms(comparisons: list[dict]) -> list[str]:
    return [f"{PROPERTY_LABELS.get(comparison['property'], comparison['property'])} "
            f"{comparison['score']:+.1f}"
            for comparison in comparisons if comparison["score"] > 0]


def _hypothesis_rationale(fid: str, ids: list[str], index: dict[str, dict],
                          comparisons: list[dict], score: float, fixed: bool) -> str:
    sources = ", ".join(f"{cid} ({index[cid]['source']})" for cid in ids)
    terms = _score_terms(comparisons)
    support = f"Scored support: {', '.join(terms)}." if terms else "No comparison contributes a positive score."
    selection = ("Retained by the fixed assignment." if fixed
                 else "Highest-scoring feasible assignment under rules-1.")
    return f"Report focus {fid} with {sources} totals {score:.1f}. {support} {selection}"


def _hypothesis_opposing(ids: list[str], index: dict[str, dict], comparisons: list[dict],
                         best_score: float, runner_score: float | None) -> list[str]:
    notes = []
    for comparison in comparisons:
        if comparison["property"] == "size_rank":
            continue
        label = PROPERTY_LABELS[comparison["property"]]
        if comparison["outcome"] == "conflict":
            notes.append(f"{label.capitalize()} conflict ({comparison['score']:+.1f}): report "
                         f"{_values(set(comparison['text']))} versus drawing {_values(set(comparison['drawing']))}.")
        elif comparison["outcome"] == "no counterpart":
            notes.append(f"{label.capitalize()} has no report counterpart "
                         f"(status '{comparison['report_status']}'); matching does not treat this as agreement "
                         "or an explicit negative.")
        elif comparison["outcome"] == "indeterminate":
            reason = ("no report observation" if comparison["report_status"] is None
                      else "no drawing evidence" if not comparison["drawing"]
                      else "no usable report value")
            notes.append(f"{label.capitalize()} is indeterminate because there is {reason}, not a negative finding.")
    for cid in ids:
        if index[cid].get("side_basis") != "explicit":
            notes.append(f"Drawing side for {cid} is inferred from view orientation; side agreement is not "
                         "independent corroboration.")
    if len(ids) > 1:
        notes.append(f"The assignment combines {len(ids)} candidates with a {EXTRA_STANDALONE_PENALTY:+.1f} split "
                     "penalty; one focus may have been split by the drawing pipeline.")
    if runner_score is not None:
        margin = best_score - runner_score
        if margin < HIGH_MARGIN:
            notes.append(f"The runner-up assignment scores {runner_score:.1f}, a margin of {margin:.1f}; "
                         "an alternative grouping remains plausible.")
    return list(dict.fromkeys(notes))


def _hypothesis_assumptions(ids: list[str], index: dict[str, dict], comparisons: list[dict]) -> list[str]:
    assumptions = []
    for comparison in comparisons:
        assumptions.extend(comparison.get("assumptions", []))
    if len(ids) > 1:
        assumptions.append("Assumes the selected candidates depict one focus split across marks, not multiple findings.")
    for cid in ids:
        for dependency in index[cid].get("depends_on", []):
            if dependency.startswith("group:"):
                assumptions.append(f"Depends on {dependency} grouping its marks as one finding; rejecting that "
                                   "grouping requires membership reassessment.")
            else:
                assumptions.append(f"Depends on reviewer membership decision {dependency}; withdrawing that "
                                   "decision requires membership reassessment.")
    return list(dict.fromkeys(assumptions))


def _report_membership_rationale(fid: str, ids: list[str], comparisons: list[dict]) -> str:
    location_comparisons = [comparison for comparison in comparisons if comparison["property"] != "size_rank"]
    agreements = [comparison for comparison in location_comparisons if comparison["outcome"] == "agreement"]
    conflicts = [comparison for comparison in location_comparisons if comparison["outcome"] == "conflict"]
    if agreements or conflicts:
        return (f"Report focus {fid} anchors candidates {', '.join(ids)}; {len(agreements)} property "
                f"comparison(s) agree and {len(conflicts)} conflict.")
    return (f"Report focus {fid} anchors candidates {', '.join(ids)}, but no location comparison is conclusive; "
            "the inclusion rests on the assignment score.")


def _diagram_membership_rationale(fid: str, cid: str, mark: str, index: dict[str, dict],
                                  comparisons: list[dict], score: float) -> str:
    candidate = index[cid]
    view = mark.split(".", 1)[0]
    location_comparisons = [comparison for comparison in comparisons if comparison["property"] != "size_rank"]
    conflicts = [comparison for comparison in location_comparisons if comparison["outcome"] == "conflict"]
    agreements = [comparison for comparison in location_comparisons if comparison["outcome"] == "agreement"]
    if conflicts:
        return (f"Mark {mark} belongs to candidate {cid} ({candidate['source']}) in the {view} view; the candidate scores "
                f"{score:.1f} against focus {fid} but has {len(conflicts)} scored conflict(s), so this membership "
                "needs review.")
    if agreements:
        properties = ", ".join(comparison["property"] for comparison in agreements)
        return (f"Mark {mark} belongs to candidate {cid} ({candidate['source']}) in the {view} view; the candidate scores "
                f"{score:.1f} against focus {fid}, with agreement on {properties}.")
    return (f"Mark {mark} belongs to candidate {cid} ({candidate['source']}) in the {view} view; no location "
            f"comparison with focus {fid} is conclusive (score {score:.1f}).")


def match(report: dict, candidates: list[dict], *,
          fixed_assignment: dict[str, list[str]] | None = None,
          previous_matching: dict | None = None) -> dict:
    """Match validated raw inputs, or materialize fixed assignments without search.

    Fixed mode permits any number of split candidates per focus. Unchanged focus
    assignments retain certainty from previous_matching's hypotheses.
    """
    foci = subjects(report, "tumour_focus")
    index = {candidate["id"]: candidate for candidate in candidates}
    if len(index) != len(candidates):
        raise ValueError("candidate IDs must be unique")
    sizes = {focus["id"]: max(dimensions_mm(observed(report, focus["id"], "dimensions")), default=0)
             for focus in foci}
    largest = max(sizes.values(), default=0)
    max_sectors = max((candidate.get("sector_count", len(candidate["sectors_in"])) for candidate in candidates), default=0)
    pairs = {}
    for focus in foci:
        for candidate in candidates:
            bonus = bool(largest and max_sectors and sizes[focus["id"]] == largest
                         and candidate.get("sector_count", len(candidate["sectors_in"])) == max_sectors)
            pairs[focus["id"], candidate["id"]] = pair_score(report, focus, candidate, bonus)

    def assignment_score(assignment: dict) -> float:
        return sum(sum(pairs[focus, cid][0] for cid in ids)
                   + EXTRA_STANDALONE_PENALTY * max(0, len(ids) - 1)
                   for focus, ids in assignment.items())

    if fixed_assignment is not None:
        unknown = set(fixed_assignment) - {focus["id"] for focus in foci}
        if unknown:
            raise ValueError(f"unknown focus IDs: {sorted(unknown)}")
        best = {focus["id"]: list(fixed_assignment.get(focus["id"], [])) for focus in foci}
        ids = [cid for ids in best.values() for cid in ids]
        if set(ids) - index.keys():
            raise ValueError("fixed assignment references unknown candidate IDs")
        if len(set(ids)) != len(ids):
            raise ValueError("a candidate can belong to at most one focus")
        marks = [mark for cid in ids for mark in index[cid]["marks"]]
        if len(set(marks)) != len(marks):
            raise ValueError("a drawing mark cannot belong to multiple assignments")
        best_score, runner, runner_score = assignment_score(best), None, None
        certainty = "medium"
        if previous_matching and best == previous_matching.get("best_assignment"):
            certainty = previous_matching["certainty"]
            previous_runner = previous_matching.get("runner_up_assignment")
            if previous_runner and all((focus, cid) in pairs for focus, ids in previous_runner.items() for cid in ids):
                runner = {focus: list(ids) for focus, ids in previous_runner.items()}
                runner_score = assignment_score(runner)
    else:
        options = [[]] + [[cid] for cid in index]
        for first, second in combinations(candidates, 2):
            if ((first.get("standalone", first["source"].startswith("standalone:"))
                 or second.get("standalone", second["source"].startswith("standalone:")))
                    and set(first["sides"]) == set(second["sides"]) and first["sides"]
                    and not set(first["marks"]) & set(second["marks"])):
                options.append([first["id"], second["id"]])
        top = []

        def search(position: int, assignment: dict, used: set, used_marks: set, score: float) -> None:
            if position == len(foci):
                top.append((score, {key: list(value) for key, value in assignment.items()}))
                top.sort(key=lambda item: -item[0])
                del top[2:]
                return
            focus_id = foci[position]["id"]
            for ids in options:
                marks = {mark for cid in ids for mark in index[cid]["marks"]}
                if used.intersection(ids) or used_marks.intersection(marks):
                    continue
                assignment[focus_id] = ids
                extra = EXTRA_STANDALONE_PENALTY if len(ids) == 2 else 0
                search(position + 1, assignment, used | set(ids), used_marks | marks,
                       score + sum(pairs[focus_id, cid][0] for cid in ids) + extra)

        search(0, {}, set(), set(), 0.0)
        best_score, best = top[0]
        runner_score, runner = top[1] if len(top) > 1 else (None, None)
        explicit = any(best.values()) and all(
            location(report, fid)["laterality"] and all(
                index[cid]["side_basis"] == "explicit"
                and sides_compatible(location(report, fid)["laterality"], set(index[cid]["sides"])) for cid in ids)
            for fid, ids in best.items() if ids)
        certainty = matching_confidence(best_score, runner_score, explicit)

    hypotheses, comparisons = [], []
    prior = {hyp["focus"]: hyp for hyp in (previous_matching or {}).get("hypotheses", [])}
    for number, focus in enumerate(foci, 1):
        fid = focus["id"]
        ids = best[fid]
        if not ids:
            continue
        level = certainty
        if fixed_assignment is not None:
            old = prior.get(fid)
            if old and set(old["candidates"]) == set(ids):
                level = old.get("certainty", (previous_matching or {}).get("certainty", "medium"))
            else:
                pair_results = [comparison for cid in ids for comparison in pairs[fid, cid][1]
                                if comparison["property"] != "size_rank"]
                level = "low" if any(c["outcome"] == "conflict" for c in pair_results) else "medium"
        hid = f"h{number}"
        score = sum(pairs[fid, cid][0] for cid in ids) + EXTRA_STANDALONE_PENALTY * max(0, len(ids) - 1)
        focus_comparisons = [dict(comparison, hypothesis=hid)
                             for cid in ids for comparison in pairs[fid, cid][1]]
        location_comparisons = [comparison for comparison in focus_comparisons
                                if comparison["property"] != "size_rank"]
        conflicts = [comparison for comparison in location_comparisons if comparison["outcome"] == "conflict"]
        memberships = [{
            "subject": "report:" + fid, "role": "report description",
            "supports": ["report:" + obs["id"] for obs in observations(report, fid)],
            "opposes": sorted({mark for comparison in conflicts
                               for mark in index[comparison["candidate"]]["marks"]}),
            "depends_on": [], "certainty": level,
            "review_status": "needs_review" if conflicts else "unreviewed",
            "rationale": _report_membership_rationale(fid, ids, focus_comparisons),
        }]
        for cid in ids:
            candidate = index[cid]
            candidate_conflicts = [comparison for comparison in pairs[fid, cid][1]
                                   if comparison["property"] != "size_rank"
                                   and comparison["outcome"] == "conflict"]
            for mark in candidate["marks"]:
                memberships.append({
                    "subject": mark, "role": "diagram depiction", "supports": [mark],
                    "opposes": sorted({ref for comparison in candidate_conflicts
                                       for ref in comparison["inputs"] if ref.startswith("report:")}),
                    "depends_on": candidate.get("depends_on", [candidate["source"]] if candidate["source"].startswith("group:") else []),
                    "certainty": level,
                    "review_status": "needs_review" if candidate_conflicts else "unreviewed",
                    "rationale": _diagram_membership_rationale(fid, cid, mark, index,
                                                               pairs[fid, cid][1], pairs[fid, cid][0]),
                })
        hypotheses.append({
            "id": hid, "focus": fid, "source_subject": "report:" + fid,
            "candidates": ids, "memberships": memberships, "score": score,
            "certainty": level, "brain": "rules", "review_status": "unreviewed",
            "rationale": _hypothesis_rationale(fid, ids, index, focus_comparisons, score,
                                               fixed_assignment is not None),
            "opposing_considerations": _hypothesis_opposing(ids, index, focus_comparisons,
                                                            best_score, runner_score),
            "assumptions": _hypothesis_assumptions(ids, index, focus_comparisons),
        })
        comparisons.extend(focus_comparisons)
    return {"hypotheses": hypotheses, "comparisons": comparisons, "best_assignment": best,
            "runner_up_assignment": runner, "total_score": best_score, "runner_up_score": runner_score,
            "certainty": certainty, "fixed_assignment": fixed_assignment is not None,
            "pair_scores": [{"focus": fid, "candidate": cid, "score": score,
                             "comparisons": comps} for (fid, cid), (score, comps) in pairs.items()]}
