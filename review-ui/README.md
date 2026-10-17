# Region review demo

Plain HTML, CSS and browser JavaScript. No build, npm dependencies, LLM calls
or REDCap connection. Use the supplied artificial hackathon data only.

## Prepare the local showcase

From the repository root:

```sh
uv run --no-project --python 3.12 python -I review-ui/prepare_showcase.py \
  --pair "preprocess/.preprocess-exports/batch-<batch-id>/<case-id>" \
  --showcase
```

Replace the example pair path with a case directory from the local preprocessing
output. Do not copy private case identifiers or paths into shared documentation.
The script verifies that the pair is listed in its artificial-data batch
manifest and that the synthetic report matches the fixture's text hash.
It copies the two existing JPGs and fixture files to ignored `.local-data/`.
Originals are untouched. The default local dictionary is
`preprocess/.preprocess-private/dictionary.json`; override with `--dictionary`.
Only the selected case's original ID and its explicit report/drawing ID evidence
are copied into ignored `.local-data/case.json`, not the full dictionary or source
paths. Missing, ambiguous, low-confidence or disagreeing IDs fail preparation.
No scan, extracted text, identity or generated case configuration is committed.

**The default analysis JSON is a complete synthetic UI example, not an analysis
of these scans.** The user-requested showcase combines it with an actual supplied
scan pair for interface development. Its manually chosen regions are explicitly
illustrative, not extracted findings. Every record carries blocking review issues
for the mismatch and invented placements. This is not a clinically matched case.

Then start the loopback-only static server, or run the VS Code task
**Serve doctor review demo**:

```sh
uv run --no-project --python 3.12 python -I -m http.server 8766 --bind 127.0.0.1 --directory review-ui
```

Open http://127.0.0.1:8766. A file URL will not work with ES modules.

## Review flow

- Equal-width source and review workspaces. The source pane stays visible while
  reviewing on desktop; smaller screens stack the panes.
- Switch between drawing, report scan and the JSON's own report text. Only one
  source appears at a time, with fit-width, 150% and 200% scan zoom and full-size
  links. The synthetic text is explicitly labelled as unrelated to the scans.
- The original source case ID is restored from the local preprocessing dictionary
  and displayed with the random pair ID retained for traceability. This is not
  an assertion of a REDCap record ID or a restored birth number.
- Two synthetic lesion records from
  [`fixtures/prefilled-analysis.json`](fixtures/prefilled-analysis.json), via
  `analysis.js`, with original JSON and evidence preserved.
- **All 12 lesion properties prefill from JSON**: histology, X/Y/Z dimensions,
  extension, perineural invasion, and primary/secondary/tertiary Gleason patterns
  and percentages. The UI marks each field "From analysis" or
  "Doctor-corrected"; the doctor reviews rather than retypes the supplied values.
- All 41 clickable regions use the documented REDCap sector codes.
- Review one lesion at a time. Switch records explicitly using lesion buttons
  or association links. Each button lists its anatomical sections and counts;
  the active record has a strong highlight and lists every assigned region code.
- Click a map sector (or use Enter/Space on it) to add/remove it for the active
  lesion immediately. Other lesions, including those sharing a sector, are
  unchanged. Undo is available for the current session's undocumented region
  edits. Pending edits are saved locally and retained across reloads, but block
  lesion confirmation and CSV export.
- Use **Document region edits** to attach evidence/reasoning to a group of edits.
  Document separate groups when they need different evidence. Cancelling this
  dialog preserves the pending edits; it does not approve them. Evidence is not
  invented from the selection polygon. Field edits still use a per-field dialog.
  Confirm requires a reason and source evidence: an exact quotation
  from the fixture report or a drag-selected crop from the verified source scan.
  Inferences are labelled and shown separately, with their reasoning.
- For empty findings or the documented "Not specified" choices, select
  "Absent / not reported" rather than inventing positive evidence.
- Add a doctor-identified lesion using report evidence; a drawing mark alone
  cannot create one. New records start empty and unreviewed. This repeating
  surgery instrument has no four-lesion limit (the four-slot form is MRI).
- Exclude a lesion with a reason, rather than deleting its source proposal.
  Exclusions remain inspectable and retained in JSON but do not produce CSV rows.
  Restore requires review again. Repeat instance numbers remain stable and are
  never reused or renumbered, including across exclusions.
- Switch lesions and inspect regions shared by multiple records.
- All 41 **editable** sectors appear once: Base, Mid, Apex, seminal vesicles and
  Urethra (atlas), with its differing mapped source title shown explicitly.
  Scalable vector outlines retain the original
  template's polygon coordinates and REDCap codes; they are not tumour contours.
- Compact axial panels keep Base/Mid/Apex in one row on wide screens, with
  smaller vesicle/sphincter panels beneath. Narrow screens reflow to two or one
  column without changing geometry, assignments or review requirements.
- One lesion can have multiple segments, including across axial levels. The
  complete set stays associated with the same lesion and exports in one row;
  editing another lesion never merges their selections.
- The collapsed **Anatomy reference — front, side & full atlas (read-only)** shows the original
  public template with the same selected sectors. It preserves an overview of
  the anatomical views without replacing the newer editor or adding duplicate
  editable controls. Its overlays are context only and cannot toggle findings.
  Coronal/sagittal drawings are context only, without coarse level buttons or
  invented projections of tumour boundaries.
- The doctor sees editable clinical values and can expand supporting source
  evidence, not a raw JSON editor. Input JSON, private review JSON download and
  CSV preview live under the collapsed **Technical tools** section below export.
- The map is monochrome: dark fill means the active lesion, light grey means
  another lesion, dashed borders mean uncertainty. Selection is not confidence.
  Region-code chips inspect assignments without toggling them. Enter/Space on
  sectors add/remove assignments; source tabs support arrow/Home/End keys.
- Inspect supplied hints/uncertainties; record a reason and choose "Reviewed and
  addressed" or "Reviewed — genuinely unknown" for every included record's flag.
  Unknown is not a positive finding or an automatic replacement value. Optional
  fields may stay empty; required fields still need a documented allowed answer.
  Sector checkboxes have no unknown code: an unresolved region association must
  be settled before export, or its lesion excluded. Retained uncertainty stays
  visible, separate from unchecked issues, and is preserved in JSON.
- Edit documented lesion properties. No clinical default is substituted for a
  missing value. Dimensions without stated axes remain unmapped; specimen-level
  grade group is not copied to lesion records.
- Explicitly confirm each lesion after edits. Region/property edits invalidate
  its confirmation and reopen resolved issues while retaining their prior reasons.
- Save locally using a case-and-input fingerprint, so changes to the source
  configuration or JSON cannot silently reuse a previous review.
- Download JSON with unchanged source analysis, the original normalized prediction,
  edits, and timestamped local decision history. This is not a secure audit store;
  the recorded local demo actor is not an authenticated doctor.
- Download a first-import lesion-only CSV for included records with explicit
  repeating instance numbers and all 41 checkbox values.

The target REDCap record ID must be entered explicitly and start with `TEST-`
or `DEMO-`. This prevents the deliberately unlinked showcase from being exported
under a real record identity. It is not the random preprocessing case ID.
The original source ID is retained in the downloaded review JSON's source
configuration, separately from that export target. Fabricated findings must not
be exported under a restored source identity.
The private dictionary stays outside the web root; preparation copies only the
selected source case's identity and supporting anchors into ignored local data.
The browser can show this local association, but does not receive the full
dictionary. No original ID is automatically written into the REDCap `record_id`
column, and restoring scan identity does not make the synthetic analysis matched.
**Download private review JSON** retains this association for local review.
Keep that file private; do not send it back to an external analysis service.

## Boundaries

The default, separately versioned **UI-only** input contract is
`doctor-review-showcase-v1`. Its JSON contains a `report_sha256`, quoted `evidence`
anchors and `lesions`. Each lesion has canonical `regions` and a `fields` object
keyed by the twelve documented REDCap lesion field names. Each supplied field
carries a raw REDCap string value, availability status, basis and evidence IDs.
The paired [synthetic report](fixtures/prefilled-report.txt) anchors the mock
values; no extraction or interpretation of the displayed scans occurs.

`showcase-analysis.js` checks the exact text hash, quotations, references, field
names, allowed choice codes and numeric ranges before prefilling. Missing or
unavailable values remain empty; inferred/calculated suggestions are separated
and require explicit review. JSON cannot mark a lesion reviewed or remove the
showcase warnings. This example does **not** change or prescribe the coworkers'
extraction/matching output contract.

`analysis.js` also retains support for the earlier report-only
`../fixtures/synthetic_response.json` fixture, including its exact report-text
hash. That limited input supplies Gleason 3+4 for focus A but no mandatory
histology/extension/perineural answers; unlabelled dimensions stay unmapped.
To run that old example, pass both `--analysis fixtures/synthetic_response.json`
and `--report-text fixtures/synthetic_report.txt` to the preparation command.
Unsupported envelopes fail explicitly.
An actual case-bound combined assessment/drawing analysis is still needed
before this can display genuine scan-derived sector predictions.
The UI does not match independent drawing marks to report foci itself.

`demo.json` is the older invented UI fixture, not the active case or an upstream
contract. General case import, source evidence highlighting, production storage,
and full preprocessing integration remain outside this slice.

Per-sector grade group is not a field in the lesion instrument. Multiple lesions
remain separate even when they share a region.

No data is uploaded. Do not use identifiable real cases: this prototype has no
authentication or production storage protections. Reset showcase removes only
the saved review for this specific case/input fingerprint.
The CSV's form status remains `0` (incomplete); review is not clinical sign-off.
This component handles only `surgery_c61_resected_lesion`, not the patient or
parent surgery forms. It is not a complete registry entry. Record identity and
remaining surgery fields must be handled elsewhere. This first-import draft
does not implement corrections/deletions of previously imported REDCap records;
omitting an excluded lesion would not delete an existing registry instance.
Lesion-only import has not been tested in live REDCap. See
[the specification](../Other/redcap/REDCAP.md), especially its open questions.

## Checks

Display labels are transcribed from the public atlas: **AFS, PZa, PZpl, PZpm,
TZa, TZp, CZ**. They are not generated by uppercasing export codes: the printed
**AFS** still exports using **`as_`**. Expanded names use the zone meanings in the
REDCap crosswalk, avoiding spelling errors in upstream titles. Raw source titles
and polygon/code associations remain unchanged for provenance.

The atlas labels key 41 **Urethra**; its mapped source title is **External urethral
sphincter**. The UI explicitly shows both source names and flags the discrepancy
for clinical confirmation. This is not a claim that the two terms are equivalent.
All sector names, sides, levels and hit areas still need doctor validation before
clinical use. See the [UX + preprocessing handoff](../Other/UX-PREPROCESS-TODO.md).

Run these in the developer console on the local page:

```js
const sectors = await (await fetch("assets/sectors.json")).json();
(await import("./tests/map-labels.test.js")).runMapLabelTests(sectors);
await (await import("./tests/redcap.test.js")).runExportTests(sectors);
const raw = await (await fetch(".local-data/analysis.json")).json();
const text = await (await fetch(".local-data/analysis-report.txt")).text();
await (await import("./tests/showcase-analysis.test.js")).runShowcaseAnalysisTests(raw, text, sectors);
(await import("./tests/review-state.test.js")).runReviewStateTests(sectors);
await (await import("./tests/ui.test.js")).runUiTests();
```

The UI tests temporarily edit the showcase, then restore its original saved
storage. **Reload the page afterwards**, even after a failed test, to discard
the in-memory test edits. Reload before tests after changing source files too,
so the browser does not reuse previously imported ES modules.

Run the local preparation checks from the repository root:

```sh
uv run --no-project --python 3.12 python -I -m unittest discover -s review-ui/tests -p 'test_*.py'
```

The anatomical template and geometry are attributed in [assets/NOTICE.txt](assets/NOTICE.txt).
