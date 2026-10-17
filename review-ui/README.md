# Doctor review workspace

Plain HTML, CSS and browser JavaScript. Open a central `combined-1` assessment,
inspect both scans, review flags and sector assignments, then download a REDCap
CSV. There is no build step, npm dependency, model call or REDCap connection.
Preprocessing is separate.

## Run

From the repository root:

```sh
python3 -I -m http.server 8766 --bind 127.0.0.1 --directory review-ui
```

Open http://127.0.0.1:8766/. A file URL cannot load the ES modules. Use HTTPS or
localhost because the browser checks SHA-256 hashes with Web Crypto.

Choose **Open a local combined assessment**, then select five local files:

1. Central's `combined.json`.
2. The exact `report.json` pinned by that output.
3. The exact `drawing.json` pinned by that output.
4. The report JPG referenced by the report extraction.
5. The drawing JPG referenced by the drawing extraction.

Files selected this way stay in the browser. Opening checks extraction hashes,
report text hash, source scan hashes, case association, source references,
availability statuses and all sector codes. Complete `report-3` and `drawing-1`
inputs are supported. Archived `report-2` inputs can be inspected through an
already-computed combined result; this does not make them valid inputs to the
current central runner. Quarantined or incomplete reports are rejected.

The page remains usable for local import if no prepared case exists.

## Prepare a local case picker

To serve already-computed artificial cases on this machine, copy only the pinned
files into the ignored web-data folder:

```sh
python3 -I review-ui/prepare_combined.py \
  /absolute/path/to/combined.json \
  --source-root /absolute/path/to/data-repo \
  --label 'Extracted report and drawing, awaiting doctor review'
```

Pass several combined paths to prepare several cases. `--source-root` resolves
relative source paths; absolute input pins are read as recorded. The helper
checks extraction and scan hashes before copying each case. It performs no OCR,
matching or external request. It refuses to overwrite a prepared case. Use a new
`--output review-ui/.local-data/<folder>` for another set; only the default
`.local-data/combined/cases.json` is loaded automatically. Other configurations
can be selected with `?case=/.local-data/<folder>/<case-id>/case.json`.

The label records the inputs' actual origin. The three cases prepared during
this PR use manual report references and extracted drawings. They are integration
probes, not measured report-extractor accuracy. Scans, copied JSON and local
review state are excluded from Git.

For Fedora access through Tailscale, an administrator on the serving machine can
add a tailnet-only HTTPS route:

```sh
sudo tailscale serve --bg --https=8447 http://127.0.0.1:8766
```

On `bigboy`, that exposes `https://bigboy.mole-tint.ts.net:8447/`. This command
needs sudo permission. An alternative from Fedora is
`ssh -N -L 8766:127.0.0.1:8766 bigboy`, then http://localhost:8766/.
Do not expose identifiable production cases through this unauthenticated server.

## Review

Choose a lesion before clicking any sector. All 41 sectors are keyboard-accessible
and use the saved registry crosswalk. Shared sectors keep independent lesion
associations. The axial editor places patient right on the viewer's left;
coronal and sagittal views are read-only reference, not projected tumour contours.
`urethra` retains the atlas/source naming disagreement for doctor inspection.

Only `sectors.in` is selected. Possible sectors stay separate and flagged. A click
stages an edit immediately; undo restores it. **Document region edits** attaches
source evidence and a reason before confirmation can proceed. Adding a lesion
requires report evidence. Unmatched drawing ink stays a case question and never
creates a lesion by itself. Excluding a lesion preserves its values and instance.

The properties pane retains source availability, basis, confidence, evidence and
alternatives. Explicit findings and inferred suggestions are shown separately.
Unresolved properties supply no selected value. Dimensions without exact named
x/y/z axes stay unmapped. Specimen grade group and classifications stay at specimen
scope. A not-reported EPE or PNI projects to the documented Not specified code;
an explicit negative projects to No. Unreadable and not-assessed values stay blank.

Flags link to review questions from affected fields and regions. **Case questions**
includes report issues, ambiguous assignments and unmatched candidates. These
questions remain even if a lesion is excluded. Information notices and drawing
details are collapsed separately and do not block export. Every included lesion
and case question needs a written decision. Retained unknowns are allowed where
the registry can represent them; sector checkboxes have no unknown code.

Fill missing surgery details and explicitly confirm the surgery record. Changes
to lesion values or regions invalidate lesion confirmation and reopen questions.
Surgery edits invalidate surgery confirmation. Required fields receive no defaults.
Enter the target REDCap `record_id` separately; the preprocessing UUID and original
printed identifier are not substitutes for that registry ID.

## Decisions and reruns

Mark assignment, membership rejection and group rejection controls create
`decisions-1` entries. Enter a reviewer name, download central decisions, and
rerun the existing central CLI against the pinned inputs:

```sh
.venv/bin/python -m central <case-id> \
  --decisions /absolute/path/to/decisions.json \
  --previous /absolute/path/to/combined.json --no-llm
```

Then open the new combined result and its pinned inputs. Matching changes block
CSV export until that new result is opened. The browser does not run the Python
matcher itself. The automated integration test verifies this round trip without
external calls.

Documented lesion property/sector edits and resolved upstream questions can also
be downloaded as central decisions. The private review JSON retains the entire
source assessment, both extraction inputs, surgery entries, exclusions, additions,
local evidence and decision history. Download it before rerunning. Surgery entries,
lesion exclusions, doctor-added lesions and UI-only confirmations have no equivalent
in central's decision contract; they stay in the review JSON. Decision export
explicitly rejects doctor-added lesions rather than dropping them silently.

Review is saved in this browser under a case-and-input fingerprint. A new combined
result starts a new review. This is local prototype storage, not an authenticated
audit system or production patient-record store.

## CSV ownership and limits

`redcap.js` remains the only CSV writer, through `buildLesionCsv`. The combined
workflow adds one non-repeating surgery row and one row per included lesion.
It retains stable repeat instance numbers, writes all 41 checkbox values, keeps
`all_sgm___1` at zero and leaves form status incomplete. A quoted text cell retains
commas and line breaks; unsafe spreadsheet prefixes are rejected. Surgery date,
branching node counts, choice codes, required fields and explicit review are checked
before export.

The CSV is a first-import draft. It creates no patient identity form, makes no
API write, and does not implement updates or deletion of existing registry rows.
Live REDCap import remains unverified. Benign findings and bilateral focus policy
remain the registry questions recorded in [REDCAP.md](../Other/redcap/REDCAP.md).
Original-ID propagation from the new preprocessing manifest into central and export
is a separate handoff TODO.

## Legacy synthetic showcase

`prepare_showcase.py --pair <paired-case-folder> --showcase` retains the earlier
fixture-only demo. It needs the local preprocessing dictionary and a matching
manifest. Its synthetic predictions are explicitly unrelated to the displayed
scans and can export only under `TEST-` or `DEMO-` IDs. If a combined case picker
exists, select `?case=/.local-data/case.json` to open that showcase.

Its exact-shape manifest check predates `preprocess-handoff-v2`; adapting that
helper is on the preprocessing handoff TODO. Use central import for the new review
workflow. The synthetic input contract and legacy report fixture remain supported
by their existing adapter tests.

## Checks

```sh
node review-ui/tests/run-unit-tests.mjs
node --test review-ui/tests/combined.test.mjs review-ui/tests/report-fixture.test.js
uv run --with httpx python -I -m unittest discover -s review-ui/tests -p 'test_*.py'
```

Python integration checks need the root project's Pydantic and httpx dependencies
and Node on PATH. The CLI-to-JavaScript-to-CLI test uses synthetic inputs and a
local central run with the model disabled.

For the prepared combined page, run in the browser console:

```js
await (await import('./tests/combined-ui.test.js')).runCombinedUiTests();
```

This changes the in-memory review temporarily and restores its earlier browser
storage. Reload afterwards, including after a failed test. The older showcase
interaction suite remains `tests/ui.test.js` and requires a prepared showcase.
Map attribution is in [assets/NOTICE.txt](assets/NOTICE.txt).
