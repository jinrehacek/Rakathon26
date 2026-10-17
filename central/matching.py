"""Exhaustive assignment and fixed-assignment materialization for decision reruns."""
from __future__ import annotations

from itertools import combinations

from .confidence import matching_confidence
from .rules import (EXTRA_STANDALONE_PENALTY, LEVEL_AGREE, LEVEL_MISSING,
                    LOCATION_AGREE, LOCATION_CONFLICT, SIDE_AGREE, SIDE_CONFLICT,
                    SIZE_RANK_BONUS, RULES_VERSION)


def subjects(report: dict, kind: str) -> list[dict]:
    return [subject for subject in report["extraction"]["subjects"] if subject["kind"] == kind]


def observations(report: dict, subject_id: str) -> list[dict]:
    return [obs for obs in report["extraction"]["observations"] if obs["subject_id"] == subject_id]


def observed(report: dict, subject_id: str, prop: str) -> dict | None:
    return next((obs for obs in observations(report, subject_id)
                 if obs["property"] == prop and obs["status"] == "recorded"), None)


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
    return result


def dimensions_mm(obs: dict | None) -> list[float]:
    if not obs:
        return []
    factors = {"mm": 1, "cm": 10}
    return [measurement["value"] * factors[measurement["unit"]]
            for measurement in obs["value"].get("measurements", [])
            if measurement["unit"] in factors]


def pair_score(report: dict, focus: dict, candidate: dict, size_bonus: bool = False) -> tuple[float, list[dict]]:
    loc = location(report, focus["id"])
    comparisons = []
    total = 0.0
    for prop, field in (("laterality", "sides"), ("level", "levels"), ("zone", "zones"),
                        ("anteroposterior", "anteroposterior")):
        text, drawing = loc[prop], set(candidate.get(field, []))
        if not text or not drawing:
            score, outcome = 0.0, "indeterminate"
        elif prop == "level":
            score = LEVEL_AGREE * len(text & drawing) + LEVEL_MISSING * len(text - drawing)
            outcome = "conflict" if text - drawing else "agreement"
        elif prop == "laterality":
            score = SIDE_AGREE if text & drawing else SIDE_CONFLICT
            outcome = "agreement" if text & drawing else "conflict"
        else:
            score = LOCATION_AGREE if text & drawing else LOCATION_CONFLICT
            outcome = "agreement" if text & drawing else "conflict"
        total += score
        obs = observed(report, focus["id"], prop)
        comparisons.append({
            "property": prop, "candidate": candidate["id"], "score": score,
            "inputs": (["report:" + obs["id"]] if obs else []) + candidate["marks"],
            "text": sorted(text), "drawing": sorted(drawing), "outcome": outcome,
            "rule": f"{RULES_VERSION}/{prop}",
            "independence_limitation": "Drawing orientation may be inferred; agreement does not establish independent corroboration.",
        })
    if size_bonus:
        total += SIZE_RANK_BONUS
    comparisons.append({"property": "size_rank", "candidate": candidate["id"],
                        "score": SIZE_RANK_BONUS if size_bonus else 0.0,
                        "outcome": "not comparable", "inputs": candidate["marks"],
                        "rule": f"{RULES_VERSION}/size_rank",
                        "explanation": "Sector count is a weak assignment tie-break, never physical size agreement."})
    return total, comparisons


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
        explicit = bool(best) and all(
            ids and location(report, fid)["laterality"] and all(
                index[cid]["side_basis"] == "explicit"
                and location(report, fid)["laterality"] & set(index[cid]["sides"]) for cid in ids)
            for fid, ids in best.items())
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
        memberships = [{"subject": "report:" + fid, "role": "report description",
                        "supports": ["report:" + obs["id"] for obs in observations(report, fid)],
                        "depends_on": [], "certainty": level}]
        for cid in ids:
            candidate = index[cid]
            memberships.extend({"subject": mark, "role": "diagram depiction", "supports": [mark],
                                "depends_on": candidate.get("depends_on", [candidate["source"]] if candidate["source"].startswith("group:") else []),
                                "certainty": level} for mark in candidate["marks"])
            comparisons.extend(dict(comparison, hypothesis=hid) for comparison in pairs[fid, cid][1])
        hypotheses.append({"id": hid, "focus": fid, "source_subject": "report:" + fid,
                           "candidates": ids, "memberships": memberships,
                           "score": sum(pairs[fid, cid][0] for cid in ids) + EXTRA_STANDALONE_PENALTY * max(0, len(ids) - 1),
                           "certainty": level, "brain": "rules", "review_status": "unreviewed"})
    return {"hypotheses": hypotheses, "comparisons": comparisons, "best_assignment": best,
            "runner_up_assignment": runner, "total_score": best_score, "runner_up_score": runner_score,
            "certainty": certainty, "fixed_assignment": fixed_assignment is not None,
            "pair_scores": [{"focus": fid, "candidate": cid, "score": score,
                             "comparisons": comps} for (fid, cid), (score, comps) in pairs.items()]}
