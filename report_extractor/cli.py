from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .extractors import ExternalExtractorDisabled, FixtureExtractor
from .ingest import IngestionError, build_text_layer
from .models import ExtractionProposal
from .pipeline import run_extraction
from .render import render_text_layer_preview


def _unique_output_dir(output_root: str | Path, prefix: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = Path(output_root).expanduser() / f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-extractor",
        description="Gemini transcription and report-3 extraction for central review.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="Create a versioned immutable text layer from text/JPEG/PNG."
    )
    ingest.add_argument("--input", required=True, type=Path)
    ingest.add_argument("--output-dir", type=Path, default=Path("Other/output"))

    commands.add_parser(
        "schema", help="Print the versioned Pydantic extraction-response JSON Schema."
    )

    run = commands.add_parser(
        "run", help="Validate an explicitly selected fixture or disabled external mode."
    )
    run.add_argument("--input", required=True, type=Path)
    run.add_argument("--mode", choices=("fixture", "gemini", "external"), required=True)
    run.add_argument("--fixture-file", type=Path)
    run.add_argument("--output-dir", type=Path, default=Path("Other/output"))
    case = commands.add_parser("case", help="Extract the manifest's report.jpg and publish its case-level report.json.")
    case.add_argument("case_id")
    case.add_argument("--manifest", type=Path, required=True)
    case.add_argument("--mode", choices=("gemini", "fixture"), default="gemini")
    case.add_argument("--fixture-file", type=Path)
    case.add_argument("--output-dir", type=Path, default=Path("Other/output/report"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "schema":
        print(json.dumps(ExtractionProposal.model_json_schema(), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "case":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", args.case_id):
                raise IngestionError("Case ID must be a single safe folder name.")
            manifest = json.loads(args.manifest.read_text())
            relative = manifest["cases"][args.case_id]["report"]
            source = (args.manifest.parent / relative).resolve(strict=True)
            expected = (args.manifest.parent / args.case_id / "report.jpg").resolve(strict=True)
            if source != expected or not source.is_relative_to(args.manifest.parent.resolve()):
                raise IngestionError("Manifest report must be <case>/report.jpg within its batch.")
            args.input = source
            args.output_dir = args.output_dir / args.case_id
        text_layer = build_text_layer(args.input)
        if args.command == "ingest":
            output = _unique_output_dir(args.output_dir, "text-layer")
            (output / "text-layer.json").write_text(
                json.dumps(
                    text_layer.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (output / "page-1-text.txt").write_text(text_layer.text, encoding="utf-8")
            (output / "review.html").write_text(
                render_text_layer_preview(text_layer), encoding="utf-8"
            )
            print(f"Saved immutable page-1 text layer and local review under {output}")
            return 0
        if args.mode == "fixture":
            if args.fixture_file is None:
                raise IngestionError(
                    "Fixture mode requires --fixture-file and exact source-text hash match."
                )
            extractor = FixtureExtractor(args.fixture_file)
        elif args.mode == "gemini":
            from .gemini import GeminiExtractor
            extractor = GeminiExtractor()
        else:
            extractor = ExternalExtractorDisabled()
        output = run_extraction(text_layer, extractor, args.output_dir)
        print(f"Mode: {extractor.mode}; local review output: {output}")
        bundle = json.loads((output / "report.json").read_text())
        if not bundle["extraction"]["complete"]:
            print("Extraction incomplete; case-level report.json was not updated.", file=sys.stderr)
            return 2
        return 0
    except (KeyError, IngestionError, OSError, ValueError, RuntimeError) as exc:
        print(f"report-extractor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
