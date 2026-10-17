# Report extractor

## Offline text-report extraction prototype

Run all commands in this guide from the repository root. Paths such as
`fixtures/`, `prompts/`, and `Other/output/` are relative to that directory.

This prototype accepts one UTF-8 plain-text report or one JPEG/PNG report image. Image inputs are processed locally with Tesseract and Czech `ces` data. PDFs, multi-page documents, drawings, matching, export, and interactive review are out of scope.

The prototype writes an immutable, versioned page-1 text layer, then accepts only an explicitly selected, hash-bound synthetic fixture response. There is no semantic regex extractor, live model adapter, or network call. Fixture output is clearly labelled and does not validate model interpretation accuracy. `prompts/report-extraction-v1.txt` and `python -m report_extractor schema` define the future provider-neutral prompt and JSON response contract.

Plain text is decoded as UTF-8 without whitespace or character normalization. Tesseract TSV words are joined with one ASCII space within each OCR line and one LF between lines; evidence offsets are half-open Python Unicode code-point offsets into that exact immutable text. OCR boxes use source-image pixels, origin at upper-left, x increasing rightward and y downward.

Install Python dependencies and the local OCR engine:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
sudo apt-get install tesseract-ocr tesseract-ocr-ces
tesseract --list-langs
```

The Tesseract language list must include `ces`. All generated report text, source-linked results, and HTML belong in `Other/output/`, which is already ignored by Git. Outputs are placed in unique run folders and do not overwrite prior attempts.

Reproduce the synthetic end-to-end fixture demo and tests:

```sh
python -m report_extractor run \
  --input fixtures/synthetic_report.txt \
  --mode fixture \
  --fixture-file fixtures/synthetic_response.json \
  --output-dir Other/output/fixture-demo
python -m unittest discover -s tests -v
```

The fixture is accepted only when its SHA-256 matches the exact immutable text layer. It produces schema-aligned `result.json`, `text-layer.json`, and a self-contained local `review.html`. The page separates valid observations, coverage, unresolved issues, and quarantined input; all report/model text is escaped. Every result starts unreviewed.

Print the versioned response JSON Schema:

```sh
python -m report_extractor schema
```

Run local OCR on the three report-only probe inputs (do not use their paired `drawing.jpg` files):

```sh
python -m report_extractor ingest \
  --input Other/preprocessed/batch-22d4f91f-fa1e-4cad-99f5-73b8245808b4/0359bf00-2223-4fd3-8bda-7aa3cc695382/report.jpg \
  --output-dir Other/output/ocr-probe
python -m report_extractor ingest \
  --input Other/preprocessed/batch-22d4f91f-fa1e-4cad-99f5-73b8245808b4/1105712e-8d9e-42bc-b161-4446601c1978/report.jpg \
  --output-dir Other/output/ocr-probe
python -m report_extractor ingest \
  --input Other/preprocessed/batch-22d4f91f-fa1e-4cad-99f5-73b8245808b4/16609ad4-7a01-40b4-a065-ae9e5b0edc4d/report.jpg \
  --output-dir Other/output/ocr-probe
```

Each OCR run writes the immutable text layer, exact text, and a local HTML preview with the source scan, word boxes, and available Tesseract confidence. Confidence describes word reading only, not medical certainty. See `Other/research/offline_text_extraction_verification.md` for the recorded probe tools, outputs, visual inspection, and limitations.

The future external mode is intentionally disabled and exits with an error before any network call:

```sh
python -m report_extractor run \
  --input fixtures/synthetic_report.txt \
  --mode external \
  --output-dir Other/output/disabled
```

Deterministic validation checks types, statuses, references, evidence quotations/offsets, declared coverage, and dependency/containment cycles. It cannot prove semantic correctness or clinical validity. No real-model extraction, model-accuracy measurement, or clinical validation is claimed. Any future provider integration and real-model accuracy evaluation remain unverified and require separate work.
