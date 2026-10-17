# JPG preprocessing MVP

Local Tesseract and Pillow, with a CLI and optional loopback upload/review UI.
No database, PDF handling or external network service.
For the supplied **artificial** hackathon scans only. Output is unreviewed and
pseudonymized, not guaranteed anonymous.

## Run

Install Tesseract locally (`brew install tesseract` on macOS), then:

```sh
cd preprocess
uv sync --python 3.12
uv run python -I preprocess.py ../Other/data --artificial-data
```

The script reads JPG/JPEG files recursively; originals are never modified.
It reads printed Rakathon IDs using local OCR, pairs one report with one drawing
by ID, rotates when needed, masks recognized IDs, and writes fresh colour JPGs
with no copied EXIF/comments/ICC profiles. It preserves leading zeros in IDs.
Filenames do not establish a match. It prints progress and aggregate counts,
not OCR text or source filenames.

OCR checks the whole page and retries a magnified bottom band because small IDs
can be missed. If the first pass cannot confidently identify the document and ID,
it retries a dense page layout, a larger bottom band and focused printed-ID line
crops. A fuzzy prefix only locates a crop; the final ID must still be literally
read by OCR, have confidence at least 70 and agree across all detected occurrences.
No OCR letter/digit substitutions or filename guesses are used for matching.
It tries other right-angle rotations if necessary. Report headings
and the drawing's Base/Mid/Apex labels suggest the document type. These are MVP
heuristics, not medical interpretation. Unreadable, duplicate, or conflicting
matches are skipped. Small-skew correction and exception review are deferred.

## Local upload and review UI

From the repository root, with local Tesseract installed:

```sh
uv run --project preprocess --python 3.12 python -I preprocess/ui.py
```

Open **http://127.0.0.1:8767/**, or run the VS Code task **Serve preprocessing
review**. This is a loopback-only, local artificial-data tool, not a production
patient-data service. No external model/API calls are made.

1. Add the report JPGs, then add the drawing JPGs before starting; picker
   selections accumulate into one upload. Confirm the pending file count and
   explicitly acknowledge artificial hackathon data. Clear selection to start over.
   **Both document types must be in the same upload**: separate processed batches
   are not automatically combined. Matching uses printed IDs, never filenames.
   Limits: 150 files, 25 MB each, 128 MB per multipart upload, 40 megapixels/image.
2. Run preprocessing. Local OCR can take several minutes; another batch cannot
   start while one is processing.
3. Select a proposed pair. Compare both original and redacted documents, zoom or
   open them full-size. Check identity matching, remaining identifiers, masks,
   orientation and preserved annotations. Originals retain their upload orientation;
   the displayed rotation describes what was applied to the redacted output.
4. **Review is optional.** Confident pairs are ready without manual confirmation.
   They remain explicitly **unreviewed**, not automatically approved. Optionally
   **Mark reviewed** after checking all three review checks, or **hold** with a
   written reason. Unknown/ambiguous inputs stay in a separate held-input list.
   This slice does not repair pairings or draw additional masks.
5. Download **ready pairs ZIP**. It contains confident, unheld pairs, their random
   case IDs and a manifest. It excludes originals, private printed IDs, mapping,
   filenames, review notes and held cases/unpaired inputs. Image hashes are
   checked again; a changed source/output must be reprocessed before handoff.

Uploads, browser-facing case snapshots, decisions and release archives stay under
ignored `.preprocess-private/ui/`. The existing pipeline still writes its private
dictionary and unreviewed `.preprocess-exports/` batch as before. The raw folder
contains all confident pairs. **Use the UI's ready-pairs ZIP if any cases have
been held**, because the ZIP respects those decisions; the raw folder is unchanged.
Use one preprocessing process at a time; do not run the CLI concurrently with a
web batch because both use the same local dictionary and latest-run diagnostics.
Do not share the private UI folder. Its review history is local and unauthenticated,
not a production clinical audit trail.

Optional approval is a human review record, **not guaranteed complete de-identification**.
The MVP recognizes Rakathon identifiers only; real personal-identifier handling
requires separate design and validation. No REDCap record or medical assessment
is produced by this preprocessing UI. See the
[UX/preprocessing checklist](../UX-PREPROCESS-TODO.md).

## Handoff

The printed output directory contains:

```text
.preprocess-exports/batch-<random-id>/
  manifest.json
  <random-case-id>/
    report.jpg
    drawing.jpg
```

Share **only that batch folder**. Its manifest maps random case IDs to the two
relative JPG paths. Downstream should retain that case ID in returned results.
Nothing is sent automatically, and there is no LLM integration.

### Downstream contract

Both the raw folder and the extracted ZIP use
`schema_version: "preprocess-handoff-v1"` with the same `cases` mapping:

```json
{
  "schema_version": "preprocess-handoff-v1",
  "data_scope": "artificial",
  "review_status": "not_reviewed",
  "cases": {
    "<random-case-id>": {
      "report": "<random-case-id>/report.jpg",
      "drawing": "<random-case-id>/drawing.jpg"
    }
  },
  "output_sha256": {
    "<random-case-id>": {
      "report": "<SHA-256 of the handed-off report JPG>",
      "drawing": "<SHA-256 of the handed-off drawing JPG>"
    }
  }
}
```

The ZIP additionally includes a `case_review` map with each case's actual
`not_reviewed` or `human_reviewed` status. Overall status is `not_reviewed`,
`partially_reviewed` or `human_reviewed`; downloading never creates a review.
The analysis team must return the **same random case ID and exact input image
hashes** with its JSON. Match by those, not row order, filenames or the printed
original ID. The original-ID dictionary stays local for reassociation.

### Connecting the first and last components

```text
Original report + drawing JPGs
  -> preprocessing: paired pseudonymized JPGs + manifest
  -> independent report and drawing extraction
  -> matching/assessment: lesion properties + region assignments + evidence/issues
  -> doctor review: inspect/correct findings
  -> first-import lesion-only REDCap CSV
```

The middle stages must retain case IDs and exact handed-off image hashes.
The combined result needs stable lesion IDs, the documented clinical fields,
canonical region codes, supporting evidence and unresolved conflicts/uncertainty.
Agree its actual JSON shape with the analysis team before implementing the final
adapter: the review UI currently demonstrates a separate synthetic showcase
contract, not a completed live connection to the extraction pipeline.

The local preprocessing and review/export components work separately. A
case-bound analysis handoff, doctor validation and an authorized REDCap test import
are still required before calling the entire pipeline finished.

### Local verification, 2026-10-17

After OCR retry fixes, the already-uploaded 80-image artificial batch produced
**40 confident pairs / 80 exported JPGs, no excluded inputs** (previously 37 pairs).
The 37 existing case IDs and pair associations were retained; uploaded original
bytes were unchanged. ZIP image hashes match the manifest, no original identifiers
are in the manifest, and optional review is honestly marked `not_reviewed`.
This is a result on this batch, not a production accuracy or anonymity guarantee.

Keep `.preprocess-private/` local:

- `dictionary.json`: original ID -> stable random case ID, source files, OCR
  quotes and mask coordinates. Reimports reuse these random IDs.
- `last-run.json`: private diagnostics for the latest batch.

Both directories are git-ignored before any output is written. The private
mapping is plaintext, not encrypted: never share or sync it. Existing SQLite
outputs from the earlier prototype are not used or deleted.

Removing recognized IDs is not a guarantee that all identifying text is removed.
TODO for a later version: broader sensitive-information checks and manual review.

## Compare originals and back-match results

From `preprocess/`, generate an offline page for a batch:

```sh
uv run python -I review.py .preprocess-exports/batch-<random-id>
```

Open the printed HTML path in your normal browser as a local file. Each case
shows the original ID, random case ID, and original/redacted report and drawing
side by side. Image links open the full-size files. Use browser Find for either
ID. Check that the pair corresponds, the ID is covered, orientation is correct,
and handwriting/annotations remain intact. Original images are not reoriented
on this page. This is a visual aid, not a recorded approval or automated proof
of complete redaction.

The page lives inside `.preprocess-private/` and references local originals.
**Never upload the review page or private dictionary.** Neither is in the
downstream batch.

Downstream returns its results with the random case ID. Locally, find that
`case_id` in `dictionary.json`; its enclosing key is the original ID and
`sources` points to the original files. The review page displays this same
relationship for manual lookup. Keep the dictionary: the random UUID does not
encode the original ID, so losing the dictionary loses the back-matching.
Automatic merging of downstream results is not implemented.

## Small synthetic check

```sh
uv run python -I -m unittest discover -s tests
```
