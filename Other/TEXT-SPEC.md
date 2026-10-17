# Text extraction spec

Updated on 2026-10-17 to replace local report OCR with Gemini transcription. Status: implementation spec. This document records the agreed behavior; writing it does not implement or verify the extractor.

## Goal and scope

Turn one Czech pathology report scan into a validated `report.json` for central matching and doctor review. Extract the report independently of its paired drawing. Matching, lesion-level inference and export belong to later steps.

[data_schema/STRUCTURE.md](../data_schema/STRUCTURE.md) is authoritative for subjects, observations, evidence, statuses and bases. [CENTRAL-SPEC.md](CENTRAL-SPEC.md#text-contract-report-3) defines the output contract, `report-3`. Keep its property tables as the single contract reference.

Implementation delivery is one PR from `main` containing the contract changes, the central changes needed to accept them, the Gemini extractor and the case-level `report.json` writer. This documentation task does not create that PR.

## Central spec changed: recheck required

We changed [CENTRAL-SPEC.md](CENTRAL-SPEC.md) from `report-2` to `report-3`. The central implementation must be rechecked against the revised spec before integration. A version-string replacement alone is insufficient.

Verified while writing this spec: `central/inputs.py` accepts only `report-2` and rejects more than one observation per subject-property pair. `report_extractor/models.py` permits only broad zones and the `unresolved_attribution` issue kind. `report_extractor/extractors.py` currently exposes fixture extraction and a disabled external extractor. These are implementation gaps, not completed changes.

The implementation recheck must cover:

- Accept only `report-3` and refuse older versions, incomplete extractions, nonempty quarantine and validation errors.
- Add exact zones `pza`, `pzpl`, `pzpm`, `tza`, `tzp`. Retain them through candidate construction, matching, comparisons and text-only sector proposals. Broad `pz` and `tz` still match their subzones.
- Accept specimen EPE, PNI, procedure, lymph-node counts and conclusion text. Specimen Gleason observations remain optional and appear only when stated.
- Preserve conflicting observations and their `internal_conflict` issue. Update consumers that currently assume one observation per property. No list-order winner is allowed.
- Carry every report issue into the doctor queue as a question, with its source context. Handwriting and OCR disagreement flags change no values.
- Keep specimen EPE/PNI observations at specimen scope. A specimen NE proposes No for each lesion as an inference requiring confirmation. A specimen ANO with several lesions becomes an attribution question. Retain contradictory focus-specific observations.
- Distinguish structurally complete output with open review issues from incomplete output. The current validator counts any issue as incomplete; that rule must change for `report-3`.
- Support image-only evidence for unreadable content and handwriting without fabricated text offsets. Recorded values still require anchored transcript quotations.
- Verify central loading of actual extractor output as well as hand-written references. Keep decision targets tied to pinned extraction inputs.

## Inputs and output files

The input is the preprocessed case's `report.jpg`; `<case>` is the ID from its preprocess `manifest.json`. The report scan is the only source document. Gemini creates its text layer.

```text
Other/output/report/<case>/<timestamp>/report.json
Other/output/report/<case>/report.json -> <timestamp>/report.json
Other/output/central-eval/<case>/report-reference.json
```

Each run gets a new directory. Its `report.json` includes `document`, `text_layer`, `extraction`, `quarantine` and `validation_errors`. Record source and text hashes, extraction ID, timestamp, extractor and prompt versions, model ID and call settings. Use `extraction.output_contract_version: "report-3"`.

Publish the case-level link only after the run bundle has been written and validated as complete. Incomplete runs remain available in their run folders and are reported as failures; they must not silently replace a usable case-level result. Central resolves the link once and pins the selected extraction and hash.

The three existing hand-written report files belong under `central-eval` as `report-reference.json`. The implementation must preserve them when separating reference data from extractor output. This spec update does not move or delete them.

`Other/output/` is already git-ignored. Do not save Gemini's raw response or a per-run copy of the prompt. Automated tests use hand-written fixture responses.

## Extraction sequence

1. Ask Gemini to act as OCR on `report.jpg` and return only verbatim text. Preserve wording, diacritics, punctuation, numbers and line breaks without correction or interpretation. Mark unreadable spans rather than guessing. Keep the resulting text layer immutable, with source dimensions, model and transcription-prompt version, and hashes. Do not invent word boxes or confidence. Retain the existing Unicode code-point offset convention. Empty, blocked or truncated responses fail without local OCR fallback.
2. Make a second Gemini call with the verbatim transcript and the same report scan. The call returns both extraction content and detected handwriting regions, conceptually `{handwriting: [...], extraction: {...}}`.
3. Convert Gemini's quotations to evidence positions in code using the minimal matcher below. Anchor quotations directly in the Gemini transcript.
4. Assign subject IDs in source order and rewrite model-local references to those IDs.
5. Validate values, scope, evidence, references and required-property coverage. If validation fails, send the errors back for one retry, using the same immutable inputs. This is one additional call, not a separate handwriting pass.
6. Validate the retry. Quarantine items that remain invalid, set `complete: false`, and retain validation errors. Central refuses that case. A transport or parse failure must not produce a complete extraction.
7. Write the run bundle and, when complete, publish the case-level link.

## Gemini settings and image use

Use model ID `gemini-3.8-flash`, temperature `0`, thinking level `low`, and the key from `GEMINI_API_KEY`. These are the agreed extractor settings. The central brain may use a higher thinking level independently.

Gemini uses its verbatim transcript for extracted values and quotations. The image provides source context and handwriting regions. There is no separate local OCR result and new extractions do not create `ocr_disagreement` issues. Historical bundles and their issues remain supported. Extraction retries reuse the same transcript; they do not transcribe again.

Handwriting detection returns regions for review. It creates a `handwriting_present` issue and no values, even if the writing appears legible. The later drawing pipeline remains separate.

The current anonymised hackathon scans may be sent to Gemini under the project agreement. This extractor choice does not select a production architecture; production requirements remain in [TASK.md](../TASK.md).

## Extraction rules

Use exactly one specimen subject, one `tumour_focus` per independently described focus, and `other_finding` for useful non-tumour findings. Include a useful finding even if its location is missing. Its unmentioned location properties are `not reported`.

Code assigns `focus-a`, `focus-b` and so on in the order the foci first appear in the text. Other findings use `other-a`, `other-b` in their own order of first appearance. Gemini's response order and dominant status do not determine IDs. Preserve the report's original labels separately. These IDs are local to the extraction; changed inputs still require central to reassess saved decisions.

Follow the required-property tables in the central contract. An unmentioned property is `not reported` with no value and a coverage-backed reason. An explicit negative is `recorded` with presence `absent`. Keep `unreadable`, `not assessed` and `not applicable` distinct.

Only explicit and normalized observations belong in this extractor. Do not derive Grade Group, invent location detail, copy specimen findings onto foci, or infer a procedure from the document type. Preserve dimensions without invented axes, percentages with their scope, and the original wording behind normalized values.

Keep specimen EPE/PNI, classifications and conclusion text at specimen scope. Specimen Gleason is optional. Extract procedure and lymph-node counts only when stated. Exact anatomical zones are allowed only when the report names them; do not turn broad PZ into a guessed PZ subzone.

If two report statements disagree about the same subject and property, retain both observations and raise `internal_conflict` referencing both. A valid conflict does not make the extraction incomplete. If attribution to a focus is ambiguous, raise `unresolved_attribution` with candidate subject IDs and no attributed value.

## Quotation matching for the first version

Code finds quotations in the immutable Gemini transcript. Gemini does not supply authoritative offsets.

1. Search for the exact quotation.
2. If exact matching fails, retry while ignoring whitespace, including line breaks. Keep a character-index map back to the original text.
3. If the successful search finds several spans, take the first in source order and raise `ambiguous_evidence` listing the candidates. This is a temporary compromise requiring review.
4. Store the matched transcript substring as `quotation` and its original code-point positions as `[start_offset, end_offset)`. The invariant is `text[start_offset:end_offset] == quotation`, including after whitespace matching.
5. If neither search finds a span, do not record the proposed value. Set the affected property to `unreadable` with no value and raise `unanchored_evidence`. Retain Gemini's proposed value and quotation inside that review issue, apart from recorded observations. Point the unavailable observation and issue to the relevant source-image region. Do not fabricate a quotation or offsets.

An unanchored quotation handled this way is a review issue and does not by itself make the case incomplete. Missing required source context or an invalid issue payload remains a validation error. There is no separate quote-repair call in this first version.

Better quoting is backlog work. The recommendations in [research/quote-anchoring.md](research/quote-anchoring.md) are research options, not requirements for this implementation.

## Verification for implementation

Use hand-written fixture model responses bound to the input text hash. Automated tests make no external calls and do not need saved live responses.

Verify the behaviors that can lose or misattribute information:

- Required coverage and unavailable statuses, including explicit NE versus an omitted property.
- Separate specimen and focus scope, optional specimen Gleason, exact versus broad zones, and non-tumour findings with no location.
- Preservation of conflicting observations, central refusal of unresolved validation failures, and complete output with open review questions.
- Exact and whitespace quotation matching with correct original offsets, repeated quotations flagged for review, and unanchored proposals kept outside recorded values.
- Handwriting issues without value changes and historical OCR disagreement compatibility.
- Verbatim Gemini transcription, source/text hashes and dimensions, with no local OCR invocation or fallback.
- IDs determined by source order when Gemini returns subjects in another order.
- One transcription call followed by one combined extraction/handwriting call, at most one validation retry, and no raw-response files.
- Timestamped output, a case-level link to the complete run, and central loading of that exact `report-3` bundle. Old contract versions must fail.
- Central's specimen EPE/PNI proposals, conflicts and doctor-confirmation requirements.

A live run on the three central probe cases can check integration. Report it as a probe, without claiming measured accuracy across the dataset. Evaluation on all 37 reports is deferred.

## Backlog

- Better quotation anchoring: numbered lines, contextual disambiguation, diacritic handling, fuzzy matching, quote-specific retry and match-quality metadata. See [quote-anchoring.md](research/quote-anchoring.md).
- A Czech phrase list in the prompt, deferred from Q9.
- Evaluation on all 37 reports, deferred from Q20.
- Saving raw Gemini responses and per-run prompt copies, if a later debugging need justifies it. It is not required now.
