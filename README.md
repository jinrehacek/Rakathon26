# ProstaPaper

ProstaPaper drafts REDCap records from typed Czech prostatectomy reports and annotated PI-RADS v2.1 drawings for doctor review. See [TASK.md](TASK.md) for the hackathon goal and scope.

## Components

### `preprocess/`

Local scan preprocessing and pseudonymization of printed Rakathon IDs. See [preprocess/README.md](preprocess/README.md).

```sh
cd preprocess && uv sync --python 3.12 && uv run python -I preprocess.py ../Other/data --artificial-data
```

The script runs without prompts. Each output case has `report.jpg`, `drawing.jpg`
and its `original_id` in a versioned manifest. Czech plus English OCR is local.
See the [handoff contract](preprocess/README.md#handoff).

### `report_extractor/`

Verbatim Gemini transcription and report extraction with evidence-backed `report-3` output. See [report_extractor/README.md](report_extractor/README.md).

```sh
python -m report_extractor run --input fixtures/synthetic_report.txt --mode fixture --fixture-file fixtures/synthetic_report3_response.json --output-dir Other/output/fixture-demo
```

### `central/`

Matches complete report and drawing extractions, retains conflicts for review, and applies doctor decisions in new runs. See [central/README.md](central/README.md).

```sh
.venv/bin/python -m central <preprocess-case-id>
```

## Project notes

Commands assume the repository root unless they change directory. The authoritative schema is [data_schema/STRUCTURE.md](data_schema/STRUCTURE.md). See [Other/redcap/REDCAP.md](Other/redcap/REDCAP.md) for REDCap fields and [Other/IMAGE_PIPELINE.md](Other/IMAGE_PIPELINE.md) for the image pipeline proposal.

The drawing pipeline is being built on a separate branch. Tests exist in `tests/` and `preprocess/tests/`.

The previous review UI has been removed for a rebuild. Its [archived documentation](Other/REVIEW-UI-ARCHIVE.md) and [UX handoff notes](Other/UX-PREPROCESS-TODO.md) remain as reference.

Supplied artificial scans in `Other/` are Git-tracked; use synthetic cases for
shared screenshots or remote demos. Keep production records local until the
hospital approves the specific purpose, lawful basis and supplier arrangement.
Consent, EU hosting or a no-training setting alone is not enough. See the [data-sharing assessment](Other/research/legal-llm-data-sharing.md).
