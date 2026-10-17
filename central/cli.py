"""Run one already-preprocessed case. Does not extract or transmit scans."""

import argparse
from pathlib import Path

from .pipeline import run_case


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", help="preprocess manifest case ID")
    parser.add_argument("--root", type=Path, help="repository/data root")
    parser.add_argument("--report", type=Path, help="explicit report-2 bundle")
    parser.add_argument("--drawing", type=Path, help="explicit drawing-1 bundle")
    parser.add_argument("--decisions", type=Path, help="decisions-1 file")
    parser.add_argument("--previous", type=Path, help="pinned previous combined.json")
    parser.add_argument("--no-llm", action="store_true", help="offline run, recorded as llm_missing")
    args = parser.parse_args(argv)
    try:
        path = run_case(args.case, root=args.root, report_path=args.report,
                        drawing_path=args.drawing, decisions_path=args.decisions,
                        previous_path=args.previous, use_llm=not args.no_llm)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"central: {exc}\n")
    print(path)
    return 0
