# ProstaPaper

ProstaPaper drafts REDCap records from typed Czech prostatectomy reports and annotated PI-RADS v2.1 drawings for doctor review. See [TASK.md](TASK.md) for the hackathon goal and scope.

## Components

### `preprocess/`

Local scan preprocessing and pseudonymization of printed Rakathon IDs. See [preprocess/README.md](preprocess/README.md).

```sh
cd preprocess && uv sync --python 3.12 && uv run python -I preprocess.py ../Other/data --artificial-data
```

Or start the local upload/review UI from the repository root:

```sh
uv run --project preprocess --python 3.12 python -I preprocess/ui.py
```

Open http://127.0.0.1:8767/. Each output case folder contains `report.jpg` and
`drawing.jpg`; the batch manifest carries random case IDs and image hashes.
Confident pairs are ready without manual confirmation; review and hold are
optional. See the [handoff contract](preprocess/README.md#downstream-contract).

### `report_extractor/`

Offline text-report extraction prototype. See [report_extractor/README.md](report_extractor/README.md).

```sh
python -m report_extractor run --input fixtures/synthetic_report.txt --mode fixture --fixture-file fixtures/synthetic_response.json --output-dir Other/output/fixture-demo
```

### `review-ui/`

Doctor review demo with REDCap lesion CSV export. See [review-ui/README.md](review-ui/README.md).

```sh
uv run --no-project --python 3.12 python -I -m http.server 8766 --bind 127.0.0.1 --directory review-ui
```

### `central/`

Matches complete report and drawing extractions, retains conflicts for review, and applies doctor decisions in new runs. See [central/README.md](central/README.md).

```sh
.venv/bin/python -m central <preprocess-case-id>
```

## Project notes

Commands assume the repository root unless they change directory. The authoritative schema is [data_schema/STRUCTURE.md](data_schema/STRUCTURE.md). See [Other/redcap/REDCAP.md](Other/redcap/REDCAP.md) for REDCap fields and [Other/IMAGE_PIPELINE.md](Other/IMAGE_PIPELINE.md) for the image pipeline proposal.

The drawing pipeline is being built on a separate branch. Tests exist in `tests/`, `preprocess/tests/`, and `review-ui/tests/`.

Supplied artificial scans in `Other/` are Git-tracked; use synthetic cases for
shared screenshots or remote demos. Keep production records local until the
hospital approves the specific purpose, lawful basis and supplier arrangement.
Consent, EU hosting or a no-training setting alone is not enough. See the [data-sharing assessment](Other/research/legal-llm-data-sharing.md).
