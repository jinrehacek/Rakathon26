# UX + preprocessing handoff

Status: 2026-10-17. Local hackathon demo, not clinically validated.

## Next session: highest priority

- [ ] Get one **real case-bound combined analysis JSON** from the analysis team.
  The current complete UI JSON is synthetic and does not describe the displayed
  scans. Obtain the corresponding report/drawing pair too.
- [ ] Agree the handoff: preprocessing's random `case_id`, both source hashes,
  stable lesion IDs, lesion properties, canonical region codes, evidence and
  uncertainty/conflict records. Reject a wrong case or changed source instead of
  attaching its analysis to another patient.
- [ ] Have a doctor check **every displayed sector name, side, level and clickable
  outline** against the atlas and the actual REDCap form. Software tests are not
  clinical validation.
- [ ] Revisit **sizes and proportions**: prostate views, region lettering, lesion
  controls and source/review panels. Agree the preferred layout, then adjust and
  test readable labels, reliable small-sector selection and desktop/mobile use.
- [ ] Resolve the naming disagreement for checkbox `urethra` / key 41: the atlas
  prints **Urethra**, while the mapped upstream title says **External urethral
  sphincter**. The UI shows both; do not silently treat them as equivalent.
- [ ] Obtain an authorized REDCap test record/project and verify a lesion-only CSV
  import, including its link to the correct patient and parent surgery.

## UX: data to get

- [ ] A complete example plus cases with missing fields, inferred suggestions,
  report/drawing disagreement, uncertain side/level, and unmatched drawing marks.
- [ ] A doctor-reviewed expected result for each test case, including the correct
  lesion-to-region association. A drawing mark alone must not create a lesion.
- [ ] Confirm the final upstream JSON contract. Do not require coworkers to emit
  the UI-only synthetic showcase format without agreement.
- [ ] Confirm ownership of patient identity, `record_id`, parent surgery fields
  and any birth-number requirement. Original source ID is not automatically the
  REDCap record ID; this component exports only the repeating lesion instrument.

## UX: what to test/check

- [ ] Load the real JSON without manual copying; verify every populated property
  and region against its source evidence. Missing findings must stay empty.
- [ ] Keep explicit findings and inferred suggestions distinguishable; require
  doctor confirmation and retain the original proposals.
- [ ] Test uncertainty handling: resolve conflicts or retain genuine unknowns
  only where REDCap supports them. Ambiguous sector checkboxes must block export.
- [ ] Test one lesion spanning Base/Mid/Apex, overlapping lesions, adding,
  excluding/restoring and switching lesions. Do not split or merge automatically.
- [ ] Verify patient-right/viewer-left orientation, all 41 code associations and
  AFS display versus `as_` export. Coronal/sagittal views stay read-only context,
  without invented lesion projections.
- [ ] Check map/text legibility, small-sector selection, keyboard operation,
  zoom, scrolling and mobile layout with a doctor.
- [ ] Check undo, grouped edit evidence, review invalidation, save/reload/reset,
  and rejection of stale or mismatched saved reviews.
- [ ] Import a reviewed multi-lesion CSV into test REDCap and inspect the actual
  saved rows: stable repeat instances, multiple checkbox selections, blank
  missing values, permitted unknown codes and incomplete form status.
- [ ] Confirm first-import-only limitations: omission of an excluded lesion
  does not delete an existing REDCap row. No direct upload is implemented.

## Preprocessing: current baseline

The earlier local run produced **37 pairs from 80 JPG inputs**; six images were
excluded. The MVP uses local OCR, pairs by printed Rakathon ID, assigns stable
random case IDs, masks recognized IDs and writes copies without copied metadata.
This is not proof of complete de-identification or production readiness.

- [ ] Investigate all six excluded images: unreadable IDs, role detection,
  missing partners, duplicate or conflicting IDs. Hold uncertain matches.
- [ ] Run a fresh nested JPG/JPEG batch and reimport it. Verify stable case IDs,
  correct report/drawing roles, no duplicate cases and unchanged original files.
- [ ] Test 90/180/270-degree rotation and separately test small skew. Inspect
  orientation and redaction coordinates, not just OCR success.
- [ ] Inspect faint pink/yellow annotations, handwriting and dimensions after
  processing. No mirroring, relevant-content cropping or aggressive thresholding.
- [ ] Visually inspect every output for remaining identifiers. The current
  Rakathon-ID mask does not handle arbitrary real personal information.
- [ ] Test unrelated files, unreadable/corrupt inputs, ambiguous IDs, repeated
  IDs and multiple pages/encounters. Decide supported formats/cardinality before
  accepting them; PDF/multipage processing is not implemented in this MVP.
- [ ] Verify ignored output/private folders before generating new data, and
  check tracked files before staging. Keep real-case content and mappings local.

## ID round-trip: must not break

- [ ] Preserve the private [ID dictionary](../preprocess/README.md#handoff)
  securely. It is plaintext and must not be shared with the analysis batch.
- [ ] Keep the random `case_id` unchanged through extraction, matching and UI.
- [ ] Test the full round-trip on several cases: original printed ID -> paired
  random ID -> analysis result -> local original-ID lookup -> correct sources.
- [ ] Verify both source hashes and fail on missing/ambiguous mappings. Test a
  deliberately swapped JSON/pair as well as a valid pair.
- [ ] Agree secure backup/access arrangements for the private dictionary.
  Losing it loses back-matching; the UUID does not encode the original ID.
- [ ] Do not restore personal identifiers into images/text sent for external
  analysis. Production de-identification and hosting approval remain separate work.

## Already checked locally

- Synthetic JSON prefills all 12 properties on both example lesions.
- Multi-region lesions export as one row each; overlapping lesions stay separate.
- CSV validation/review gates and UI interactions have synthetic test coverage.
- The local source-ID dictionary exists; the showcase's lookup was checked
  previously. Automatic batch integration with actual downstream JSON is pending.
- Display labels now use atlas lettering: **AFS, PZa, PZpl, PZpm, TZa, TZp, CZ**.
  Export codes, raw source titles and the canonical polygon geometry are unchanged.

See [preprocessing usage](../preprocess/README.md),
[review UI usage](../review-ui/README.md) and
[REDCap specification](redcap/REDCAP.md).
