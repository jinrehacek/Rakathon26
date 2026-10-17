"""Score a non-expert three-case probe, retaining uncertainty and missing brains."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .candidates import crosswalk_rows, sector_sets


def jaccard(first: set, second: set) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 1.0


def _llm_sectors(drawing: dict, marks: set[str]) -> set[str]:
    views = {view["id"]: view for view in drawing["views"]}
    rows = crosswalk_rows()
    result = set()
    for mark in drawing["marks"]:
        view = views[mark["view"]]
        if mark["id"] in marks and (view["id"] in {"base", "mid", "apex"}
                                      or view["view_type"] in {"axial", "cross-sectional", "cross_sectional"}):
            selected, _ = sector_sets(mark, rows)
            result.update(selected)
    return result


def score_case(labels: dict, combined: dict, drawing: dict) -> dict:
    """Compare each reader with labels without silently scoring uncertain labels."""
    if not labels.get("non_expert"):
        raise ValueError("probe labels must declare non_expert=true")
    if labels["case_id"] != combined["case_id"]:
        raise ValueError("reference labels belong to another case")
    for name in ("report", "drawing"):
        if labels["inputs"][name]["sha256"] != combined["inputs"][name]["sha256"]:
            raise ValueError(f"{name} reference labels do not match the pinned run")
    if combined.get("decisions_applied"):
        raise ValueError("reviewed runs cannot be scored as automatic accuracy; evaluate an unreviewed run")
    assignment = combined["matching"]["hypotheses"]
    rules = {hyp["focus"]: {m["subject"] for m in hyp["memberships"] if m.get("role") == "diagram depiction"}
             for hyp in assignment}
    rule_sectors = {lesion.get("focus"): set(lesion["sectors"]["in"]) for lesion in combined["lesions"]}
    brain = combined["brains"]["llm"]
    current_llm = brain.get("status") == "ok" and brain.get("input_hashes_match") is True
    llm = {item["focus"]: set(item["marks"]) for item in brain.get("assignments", [])} if current_llm else {}
    readers = {"rules": (rules, True), "llm": (llm, current_llm)}
    scores = {}
    for name, (assignments, available) in readers.items():
        items = []
        for label in labels["assignments"]:
            item = {"focus": label["focus"], "uncertain": bool(label.get("uncertain")),
                    "reason": label.get("reason", ""), "scored": available and not label.get("uncertain")}
            if item["scored"]:
                actual = assignments.get(label["focus"], set())
                sectors = rule_sectors.get(label["focus"], set()) if name == "rules" else _llm_sectors(drawing, actual)
                item.update(assignment_correct=actual == set(label["marks"]),
                            sector_jaccard=jaccard(sectors, set(label["sectors"])),
                            predicted_marks=sorted(actual), predicted_sectors=sorted(sectors))
            items.append(item)
        scored = [item for item in items if item["scored"]]
        scores[name] = {"available": available, "items": items, "scored_foci": len(scored),
                        "correct_assignments": sum(item["assignment_correct"] for item in scored),
                        "mean_sector_jaccard": sum(item["sector_jaccard"] for item in scored) / len(scored) if scored else None}
    rules_issues = combined["brains"]["rules"].get("issues", [])
    llm_issues = brain.get("issues", []) if current_llm else []
    counts = {"rules": dict(Counter(issue["kind"] for issue in rules_issues)),
              "llm": dict(Counter(issue["kind"] for issue in llm_issues))}
    return {"case_id": labels["case_id"], "scores": scores, "issue_counts": counts,
            "issue_kinds_only_rules": sorted(counts["rules"].keys() - counts["llm"].keys()),
            "issue_kinds_only_llm": sorted(counts["llm"].keys() - counts["rules"].keys()),
            "uncertain_foci": sum(bool(label.get("uncertain")) for label in labels["assignments"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--case", action="append", dest="cases", help="case ID, repeat for several cases")
    args = parser.parse_args(argv)
    output_root = args.root / "Other/output/central-eval"
    cases = args.cases or sorted(path.parent.name for path in output_root.glob("*/labels.json"))
    if not cases:
        parser.error("no case reference labels found")
    from .inputs import load_drawing
    scores = []
    for case in cases:
        labels = json.loads((output_root / case / "labels.json").read_text())
        combined = json.loads((args.root / "Other/output/combined" / case / "latest/combined.json").resolve().read_text())
        drawing_file = Path(combined["inputs"]["drawing"]["path"])
        from .inputs import sha256_file
        if sha256_file(drawing_file) != combined["inputs"]["drawing"]["sha256"]:
            raise ValueError("drawing no longer matches the evaluated run")
        scores.append(score_case(labels, combined, load_drawing(drawing_file)))
    summary = {"kind": "non-expert probe", "cases": scores,
               "limitations": ["Three cases are a probe, not an accuracy estimate.",
                               "The same reader wrote report inputs and labels; cleaner inputs can flatter both brains.",
                               "Uncertain labels and unavailable LLM readings are excluded from scored aggregates."]}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = output_root / (stamp + "-scores.json")
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
