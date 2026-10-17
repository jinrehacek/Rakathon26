"""Run the drawing pipeline on preprocess-batch cases and write drawing.json.

    uv run --extra drawing --env-file .env python -m drawing_pipeline run --manifest <batch>/manifest.json --case <id>
    uv run --extra drawing python -m drawing_pipeline grade --round 1 --case <id> ...

Every Gemini call sends a scan to Google. AGENTS.md: only when the user has said so
in the current session. --replay rebuilds from saved responses with no API call.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import compare, cv_regions, gemini, grading, grouping, llm, merge, notes, orientation, output, polygon_sectors, preprocess
from .models import GEMINI_MODEL, THRESHOLDS, Extraction
from .reference import ROOT, VIEWS

OUTPUT_ROOT = ROOT / "Other/output/drawing"


def git_sha() -> str | None:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "drawing_pipeline", "prompts"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def run_case(case_id: str, drawing: Path, args) -> Path:
    out = args.output / case_id
    views = args.views
    if args.replay and (out / "preprocess/metadata.json").is_file():
        metadata = json.loads((out / "preprocess/metadata.json").read_text())
    else:
        metadata = preprocess.prepare(drawing, out, hysteresis=not args.no_hysteresis)

    key = None if args.replay else llm.api_key()
    with httpx.Client(timeout=args.timeout) as client, ThreadPoolExecutor(max_workers=1) as pool:
        # Gemini and CV are independent machines: Gemini gets no CV output, CV gets no Gemini output.
        readings = pool.submit(gemini.read_case, out, views, client=client, key=key, model=args.model,
                               runs=THRESHOLDS["runs"], replay=args.replay)
        found, masks, overlays = {}, {}, {}
        for view in views:
            original, cleaned, mask = preprocess.load_view(out, view)
            found[view] = cv_regions.analyse_view(mask, view)
            masks[view] = mask
            overlays[view] = cv_regions.overlay(cleaned, found[view])
        readings = readings.result()

        marks, signals, runs_completed = [], [], {}
        for view in views:
            runs_completed[view] = sum(run is not None for run in readings[view])
            merged, merge_signals = merge.merge_runs(view, readings[view])
            signals += merge_signals
            signals += polygon_sectors.apply(merged)
            merged, compare_signals = compare.compare_view(view, merged, found[view], masks[view])
            signals += compare_signals
            marks += merged

        orientations, letters, orientation_signals = orientation.orient_views(marks)
        signals += orientation_signals
        orientation.apply_sides(marks, orientations)
        signals += notes.link_notes(marks)

        groups, standalone, not_lesion, grouping_signals = grouping.run_grouping(
            out, marks, orientations, client=client, key=key, model=args.model, replay=args.replay)
        signals += grouping_signals  # includes the code checks

    extraction = Extraction(
        case_id=case_id, source_path=metadata["source"], source_sha256=metadata["source_sha256"],
        timestamp_utc=datetime.now(timezone.utc).isoformat(), git_sha=git_sha(), model=args.model,
        prompt_sha256={"drawing": gemini.prompt_sha256(), "grouping": grouping.prompt_sha256()},
        thresholds=THRESHOLDS | {"preprocess": metadata["parameters"], "hysteresis": metadata["hysteresis"]},
        alignment={k: metadata["alignment"][k] for k in ("method", "inliers", "median_px", "p95_px")},
        runs_completed=runs_completed,
        notes=["Diagram marks are not lesions. Groups are within-document matching hypotheses.",
               "Signals are not flags; the central system decides.",
               *(["Rebuilt from saved Gemini responses (--replay)."] if args.replay else [])])
    views_out = [output.view_out(view, orientations[view], letters.get(view, [])) for view in views]
    cv_out = [item.region for view in views for item in found[view]]
    result = output.build_output(extraction, views_out, marks, cv_out, groups, standalone, not_lesion, signals)
    path = out / "drawing.json"
    output.write(result, path)
    if args.sheets:
        grading.make_sheets(out, result, overlays)
    print(f"{case_id}: {len(marks)} marks, {len(groups)} groups, {len(result.signals)} signals -> {path.relative_to(ROOT)}")
    return path


def cmd_run(args) -> int:
    cases = preprocess.load_manifest(args.manifest)
    selected = list(cases) if args.all else args.case
    missing = [case for case in selected if case not in cases]
    if missing or not selected:
        sys.exit(f"Unknown or no cases: {missing or 'pass --case or --all'}")
    failures = 0
    for case_id in selected:
        try:
            run_case(case_id, cases[case_id], args)
        except (ValueError, RuntimeError, OSError) as error:
            failures += 1
            print(f"{case_id}: failed: {error}", file=sys.stderr)
    return 1 if failures else 0


def cmd_grade(args) -> int:
    outputs = []
    for case_id in args.case:
        out = args.output / case_id
        result = output.load(out / "drawing.json")
        overlays = {}
        for view in [v.id for v in result.views]:
            _, cleaned, mask = preprocess.load_view(out, view)
            overlays[view] = cv_regions.overlay(cleaned, cv_regions.analyse_view(mask, view))
        print(grading.make_sheets(out, result, overlays))
        outputs.append(result)
    print(grading.write_template(outputs, args.round))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="drawing_pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the pipeline and write drawing.json")
    run.add_argument("--manifest", type=Path, required=True, help="Preprocess batch manifest.json")
    run.add_argument("--case", nargs="+", default=[], help="Case IDs from the manifest")
    run.add_argument("--all", action="store_true", help="Every case in the manifest")
    run.add_argument("--views", nargs="+", default=list(VIEWS), choices=list(VIEWS))
    run.add_argument("--model", default=GEMINI_MODEL)
    run.add_argument("--replay", action="store_true", help="Rebuild from saved Gemini responses; no API call")
    run.add_argument("--no-hysteresis", action="store_true", help="Old single-threshold ink mask")
    run.add_argument("--sheets", action="store_true", help="Also write grading sheets")
    run.add_argument("--timeout", type=float, default=240)
    grade = sub.add_parser("grade", help="Grading sheets and a round-<n>.md template from existing drawing.json")
    grade.add_argument("--case", nargs="+", required=True)
    grade.add_argument("--round", type=int, required=True)
    for p in (run, grade):
        p.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if not args.output.resolve().is_relative_to((ROOT / "Other/output").resolve()):
        parser.error("Outputs must stay under the git-ignored Other/output folder")
    return cmd_run(args) if args.command == "run" else cmd_grade(args)


if __name__ == "__main__":
    raise SystemExit(main())
