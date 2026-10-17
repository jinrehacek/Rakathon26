# Report extraction

The extractor reads one Czech report independently of its drawing and writes the
`report-3` bundle defined in [CENTRAL-SPEC.md](../Other/CENTRAL-SPEC.md). See
[TEXT-SPEC.md](../Other/TEXT-SPEC.md) for extraction rules.

Run from the repository root. Image ingestion requires local Tesseract with Czech
`ces` language data. Check it with `tesseract --list-langs`.

```sh
uv sync --extra drawing
sudo apt-get install tesseract-ocr tesseract-ocr-ces
uv run --env-file .env python -m report_extractor case <case-id> \
  --manifest Other/preprocessed/<batch>/manifest.json
```

The case command selects `<case-id>/report.jpg` from the manifest. It sends that
scan and its immutable local OCR text to Gemini in one combined extraction and
handwriting request. Settings are `gemini-3.8-flash`, temperature `0`, thinking
level `low`, with `GEMINI_API_KEY` from the environment. Validation can trigger
one additional call with the same inputs and error feedback.

Each attempt writes to `Other/output/report/<case>/<timestamp>/`. The run contains
`report.json`, `text-layer.json`, and a local `review.html`. `result.json` links to
`report.json` for the original diagnostic workflow. All generated data stays in
Git-ignored `Other/output/`. Raw Gemini responses and prompt copies are not saved.

Only complete, validated runs replace the relative case-level `report.json` link.
An incomplete run exits with code 2 and leaves the previous result available.
Open review questions do not make an otherwise valid extraction incomplete.
Central resolves the case link once and pins the selected extraction and hash.
Before replacing a manual probe input, the writer preserves its bytes under
`Other/output/central-eval/<case>/report-reference-original.json` and creates
`report-reference.json` if absent. An old reference needs a separate reviewed
`report-3` migration before central can load it. Existing references are preserved.

Code anchors model quotations in the OCR text using exact matching followed by
whitespace-insensitive matching. Offsets refer to original Unicode code points.
Repeated matches use the first span and raise a question. An unanchored proposal
becomes `unreadable`; its proposed value and quotation stay in the issue. Image-only
evidence needs a source region and cannot support a recorded value.

Handwriting and OCR disagreements produce questions without changing field values.
Conflicting statements keep all observations. Foci and other findings get IDs in
source order. Specimen statements retain their scope.

For a synthetic fixture run with no network:

```sh
uv run python -m report_extractor run \
  --input fixtures/synthetic_report.txt --mode fixture \
  --fixture-file fixtures/synthetic_report3_response.json \
  --output-dir Other/output/fixture-demo
uv run pytest tests -q
```

The extractor uses `synthetic_report3_response.json`; the original
`synthetic_response.json` remains the legacy UI demonstration fixture.
Fixtures declare their prompt/contract versions and exact text hash. Tests inject
hand-written combined model responses through the same Gemini adapter. They cover
retry bounds, evidence anchoring, source ordering, issue retention, publication,
and central loading. They do not measure model accuracy.

For OCR alone, use `ingest --input <report.jpg> --output-dir Other/output/ocr`.
For an already selected scan, `run --input <report.jpg> --mode gemini
--output-dir Other/output/report/<case>` uses the same writer. The legacy
`external` mode remains disabled. `schema` prints the anchored output graph schema;
the Gemini adapter's `response_schema()` describes its pre-anchoring response.

Production provider and hospital approval requirements remain in
[TASK.md](../TASK.md). The current hackathon scans are authorised for Gemini;
that agreement does not select a production service.

## Verification

Verified on 2026-10-17: 291 Python tests and 38 subtests in `tests/`, 14
preprocessing/showcase tests and 5 subtests, and the Node test suite pass. The
Node suite includes the legacy report-only adapter's nine checks.

All three live hackathon probe cases produced complete `report-3` bundles.
Central loaded each resolved run, verified its pinned hash and wrote a combined
draft with its review questions retained. The central probe used the rules brain
without another model call. Original manual references remain archived, and their
separate `report-3` reference versions pass validation. The local probe summary
and generated records stay under ignored `Other/output/`.

This checks integration. Model accuracy and doctor agreement have not been measured.
