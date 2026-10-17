# JPG preprocessing MVP

One script using local Tesseract and Pillow. No UI, database, PDF handling, or network API.
For the supplied **artificial** hackathon scans only. Output is unreviewed and
pseudonymized, not guaranteed anonymous.

Python 3.12 and `uv` manage the environment. Pillow handles image work; the
standard library writes the manifest, private dictionary and random case IDs.
Dependencies are declared in [pyproject.toml](pyproject.toml) and locked in
[uv.lock](uv.lock).

## Run

Install Tesseract locally (`brew install tesseract` on macOS), then:

```sh
cd preprocess
uv sync --python 3.12
uv run python -I preprocess.py ../Other/data --artificial-data
```

## Platform support

Install Tesseract separately from Python. This script uses English data (`eng`)
and has no language-selection option. The Python lockfile does not pin the
Tesseract engine or its language data.

- macOS: `brew install tesseract`
- Debian or Ubuntu: `sudo apt install tesseract-ocr`
- Windows: use the [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html) and add its binary directory to `PATH`.

The recorded run was on macOS. Linux and Windows have not been validated.

The script reads JPG/JPEG files recursively; originals are never modified.
It reads printed Rakathon IDs using local OCR, pairs one report with one drawing
by ID, rotates when needed, masks recognized IDs, and writes fresh colour JPGs
with no copied EXIF/comments/ICC profiles. It preserves leading zeros in IDs.
Filenames do not establish a match. It prints progress and aggregate counts,
not OCR text or source filenames.

OCR checks the whole page and retries a magnified bottom band because small IDs
can be missed. It tries other right-angle rotations if necessary. Report headings
and the drawing's Base/Mid/Apex labels suggest the document type. These are MVP
heuristics, not medical interpretation. Unreadable, duplicate, or conflicting
matches are skipped. Small-skew correction and exception review are deferred.

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

Keep `.preprocess-private/` local:

- `dictionary.json`: original ID -> stable random case ID, source files, OCR
  quotes and mask coordinates. Reimports reuse these random IDs.
- `last-run.json`: private diagnostics for the latest batch.

Both directories are git-ignored before any output is written. The private
mapping is plaintext, not encrypted: never share or sync it. Existing SQLite
outputs from the earlier prototype are not used or deleted.
The script checks with Git that these directories are ignored and untracked
before writing.

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

## Synthetic checks

The five checks cover identifier parsing, drawing classification, redaction
pixels, stable pair exports, and links from the private comparison page. A prior
local run on 80 artificial JPGs produced 37 pairs. All 37 pairings agreed with
filename numbers, and six images were excluded. This checks pairing against a
filename proxy only. It does not establish complete identifier removal or
anonymity. Investigating the excluded images and testing small rotation/skew
cases remain follow-up work.

```sh
uv run python -I -m unittest discover -s tests
```
