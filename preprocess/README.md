# JPG preprocessing script

Run local OCR, pair report and drawing by their printed Rakathon ID, mask the ID
in output copies and write a manifest. The command runs without prompts. There
is no preprocessing web UI or HTML comparison-page generator.

This version handles the supplied artificial hackathon scans. It does not detect
rodné číslo or remove every kind of personal information. That work is separate.

## Run

Install Python 3.12, uv and Tesseract with Czech and English trained data.
On Debian or Ubuntu:

```sh
sudo apt install tesseract-ocr tesseract-ocr-ces tesseract-ocr-eng
```

On macOS, use `brew install tesseract tesseract-lang`. Windows has not been tested.
The Python environment does not pin the Tesseract engine or its language data.

From the repository root:

```sh
uv sync --project preprocess --python 3.12
uv run --project preprocess --python 3.12 python -I preprocess/preprocess.py Other/data --artificial-data
```

Tesseract uses `-l ces+eng`. The script scans JPG/JPEG files recursively and leaves
originals unchanged. Both document types must be in the input folder tree. It
pairs by the literal printed ID, never by filename. Leading zeros are retained.
Missing, conflicting, weak or duplicate matches are excluded from the output.

OCR retries page layout, the bottom band and focused ID crops before excluding
an uncertain input. Similarity only locates a crop; it never repairs or guesses
an ID. An accepted ID must be read literally, score at least 70 and agree across
all recognised occurrences. Right-angle rotations are supported; small-skew
correction and PDF/multipage input are outside this version.

Each successful run prints one JSON summary to stdout, with `pairs`, `issues`
and `bundle`. Progress goes to stderr without identifiers or OCR text. A fatal
error or zero confident pairs exits with status 2. A partially paired batch
returns status 0; callers must inspect `issues` before releasing its output.

## Background use

The CLI can run in a background job. No scheduler is installed by this PR.
Use absolute paths and prevent overlapping runs because the dictionary and
latest-run diagnostics are shared. On Linux, after creating the environment,
a future cron or worker command can use:

```sh
flock -n /tmp/prostapaper-preprocess.lock \
  /absolute/repo/preprocess/.venv/bin/python -I \
  /absolute/repo/preprocess/preprocess.py /absolute/input-folder --artificial-data
```

Replace the example paths. This scheduling example has not been installed or run.
Repeated runs process all inputs again and write a new batch while reusing case
IDs. An inbox policy for completed batches and processed inputs is future work.
The script does not delete or move input scans.

## Handoff

The printed output directory contains:

```text
.preprocess-exports/batch-<random-id>/
  manifest.json
  <random-case-id>/
    report.jpg
    drawing.jpg
```

The `preprocess-handoff-v2` manifest includes the original printed ID per pair:

```json
{
  "schema_version": "preprocess-handoff-v2",
  "data_scope": "artificial",
  "review_status": "not_reviewed",
  "cases": {
    "<random-case-id>": {
      "original_id": "Rakathon05",
      "report": "<random-case-id>/report.jpg",
      "drawing": "<random-case-id>/drawing.jpg"
    }
  },
  "output_sha256": {
    "<random-case-id>": {
      "report": "<SHA-256 of report.jpg>",
      "drawing": "<SHA-256 of drawing.jpg>"
    }
  }
}
```

`original_id` is retained for downstream reassociation and REDCap preparation.
It is not a REDCap `record_id`, and a Rakathon ID is not a birth number.
This changes the earlier manifest's identity boundary: images have masked IDs,
but the batch manifest now carries their original association. Keep the bundle
within its authorised workflow. Nothing is transmitted automatically.

Downstream must retain the random case ID and exact output image hashes. Metadata
such as `original_id` is not an image path. The doctor-review preparation helper's
old exact-shape check still needs updating, as recorded in the
[handoff TODO](../Other/UX-PREPROCESS-TODO.md#id-round-trip-must-not-break).
Propagation through central, doctor review and REDCap remains on that TODO.

The local dictionary under `.preprocess-private/dictionary.json` retains the
original ID, stable random case ID, source files, OCR evidence and mask boxes.
`last-run.json` holds the latest private diagnostics. Both private and output
folders must be ignored and untracked before the script writes to them. The
mapping is plaintext. No scans, mappings or generated batches belong in Git.

## Checks

```sh
uv run --project preprocess --python 3.12 python -I -m unittest discover -s preprocess/tests
```

Tests cover literal IDs, leading zeros, Czech plus English OCR arguments, retry
behaviour, confidence and conflict handling, mask coordinates, unchanged source
pixels, stable case IDs, original IDs in the manifest and exact output hashes.

The Linux run on `Other/data` with Tesseract 5.5.0 paired 40 of 40 cases from 80
scans, with 0 filename mismatches, no skipped cases and no reported issues. All
80 original hashes and 80 output hashes were checked. The fresh v2 run also
verified all 40 manifest original IDs and preserved every prior random case ID. Filename numbers were used
only as a diagnostic after pairing. The user-supplied main comparison was 38 of
40, with 0 mismatches and cases 5 and 8 skipped; it was not rerun here.
These results test pairing on this batch, not complete identifier removal.
