# Central system spec

Agreed in a grilling session on 2026-10-17. Status: spec, nothing built yet.

## Goal

The central system takes one case's report extraction and its `drawing.json`, decides what they mean together, and writes `combined.json`. It is steps 3 and 4 of the pipeline: matching (`data_schema/MATCHING.md`) and the combined interpretation (`data_schema/ASSESSMENT.md`).

The drawing pipeline mines everything it can from the sheet. Its groups, sectors and signals are input, not decisions. The central system decides:

- which text focus each drawing mark belongs to
- which sectors each lesion gets
- how confident we are in each result, mainly from text vs drawing agreement
- which issues reach the doctor
- which consistency checks fail

Out of scope here:

- Building the text extractor. This spec only fixes its output contract (section "Text contract"); a separate effort builds it.
- The UI and the REDCap CSV (step 5). Section "Step 5 constraints" lists what this spec must not make harder.

`data_schema/STRUCTURE.md` stays authoritative. Nothing in this spec conflicts with it, MATCHING.md or ASSESSMENT.md.

## Terms

| Term | Meaning |
| --- | --- |
| Focus | A tumour focus subject in the report extraction. |
| Candidate | One drawing group or one standalone mark from `drawing.json`. A candidate is never a lesion on its own. |
| Lesion | A finding interpretation in `combined.json`. Becomes one REDCap `surgery_c61_resected_lesion` instance. |
| Brain | One way of deciding. Two brains run on every case: rules (code) and LLM (Gemini). |
| Issue | Something the doctor sees. Severity `question` or `info`. |
| Decision | A doctor's change, saved in `decisions.json` and fed back to the central system. |

## Inputs and outputs

```
Other/output/report/<case>/report.json      text extraction, contract report-2 (below)
Other/output/drawing/<case>/drawing.json    drawing pipeline output, schema_version drawing-1
Other/output/combined/<case>/decisions.json optional, doctor decisions
            │
            ▼
        central/
            │
            ▼
Other/output/combined/<case>/<timestamp>/combined.json
Other/output/combined/<case>/latest -> <timestamp>
```

`<case>` is the case ID from the preprocess `manifest.json`. `/Other/output/` is already git-ignored.

Rules:

1. Validate both inputs strictly. Refuse a `drawing.json` whose `extraction.schema_version` is not `drawing-1` or that fails `DrawingOutput` validation. Refuse a report extraction whose contract version is not `report-2`.
2. Pin inputs by ID and SHA-256 in `combined.json`. Never resolve to "latest" while running.
3. Each run writes a new timestamped folder. Old runs stay.

### Document pairing

A report and a drawing in the same preprocess case folder are paired with basis `supplied association` and certainty `high`. The pairing is recorded in `combined.json` as MATCHING.md requires.

## Text contract (`report-2`)

What the central system needs from the text extractor. The text extractor builds against this section.

### Envelope

Same bundle as `report_extractor/pipeline.py` writes today: `document`, `text_layer`, `extraction`, `quarantine`, `validation_errors`. Changes:

- `extraction.output_contract_version` is `report-2`.
- `extraction.complete` must be `true`. The central system refuses incomplete extractions.
- The file is `Other/output/report/<case>/report.json`, one per case. Today's extractor writes timestamped `result.json` folders instead; the text part writes or links the case file.

`report-2` extends `report_extractor/models.py`. Evidence, subjects, statuses, bases, certainty and the observation rules (recorded needs a value and direct evidence, `not reported` needs a reason and no quotation) stay as they are. The value types and properties change as listed under "Changes to models.py". Every recorded observation has at least one evidence anchor with the exact Czech quotation and code-point offsets into the text layer.

### Changes to models.py

Add to `ObservationProperty`: `reported_label`, `dominant`, `laterality`, `level`, `zone`, `anteroposterior`, `extraprostatic_extension`, `perineural_invasion`, `histology_type`, `classification_pn`, `classification_pm`, `reported_lesion_count`, `multifocality`, `histology`, `icd_o`, `seminal_vesicle_invasion`, `finding_type`. Add each to `PROPERTY_VALUE_TYPES` with the value type in the tables below.

Add `OTHER_FINDING` subjects to what the extractor may return. The kind already exists in `SubjectKind`.

Replace `LocationValue` with a value whose components are all optional. A location observation sets only the component its property names:

```json
{"type": "location", "laterality": "left", "original_wording": "v levém laloku"}
{"type": "location", "levels": ["apex", "mid"], "original_wording": "apikálně a ve středu"}
{"type": "location", "zones": ["pz"], "original_wording": "v periferní zóně"}
{"type": "location", "anteroposterior": "posterior", "original_wording": "dorzálně"}
{"type": "location", "description": "levý lalok, apex, periferní zóna", "original_wording": "..."}
```

| Component | Values |
| --- | --- |
| `laterality` | `right`, `left`, `bilateral`, `midline` |
| `levels` | list of `base`, `mid`, `apex` |
| `zones` | list of `pz`, `tz`, `cz`, `as`, `sv` |
| `anteroposterior` | `anterior`, `posterior` |
| `description` | free text, used only by `textual_location` |

Extend `GleasonPatternsValue` with an optional tertiary pattern and an optional percentage per pattern. Percentages refer to the focus the observation describes.

```json
{"type": "gleason_patterns",
 "primary": {"pattern": 3, "percent": 60},
 "secondary": {"pattern": 4, "percent": 35},
 "tertiary": {"pattern": 5, "percent": 5},
 "original_wording": "..."}
```

Add two value types:

```json
{"type": "text", "text": "Ložisko A", "original_wording": "Ložisko A"}
{"type": "quantity", "value": 2, "unit": null, "approximate": false, "original_wording": "dvě ložiska"}
```

`coded` values for `histology_type` and `histology` put the REDCap choice code in `code` and keep `original_wording`. `multifocality` uses `code` `multifocal` or `unifocal`.

### Coverage

For every subject, every property listed for its kind below gets an observation. A property the report does not mention gets status `not reported` with no value. An explicit negative is `recorded` with presence `absent`. Unreadable and not assessed stay distinct. A missing observation is a contract violation, not "not reported".

### Subjects

| Kind | When |
| --- | --- |
| `specimen` | Always exactly one. |
| `tumour_focus` | One per focus the report describes, labelled or not. A report that describes one tumour without a label still yields one focus. |
| `other_finding` | One per non-tumour finding with a location, for example zánět. |

### Focus properties

| Property | Value type | Content |
| --- | --- | --- |
| `reported_label` | text | Label as written, for example "Ložisko A". `not reported` if unlabelled. |
| `dominant` | presence | Present only if the report calls this focus dominant or main. |
| `laterality` | location | `right`, `left`, `bilateral` or `midline`, with original wording ("v levém laloku", "P lalok"). |
| `level` | location | One or more of `base`, `mid`, `apex`. |
| `zone` | location | One or more of `pz`, `tz`, `cz`, `as`, `sv`. Use `as` for AFS. |
| `anteroposterior` | location | `anterior` or `posterior`. |
| `textual_location` | location | The full location phrase unchanged. Kept for the doctor. |
| `dimensions` | dimensions | As today: ordered measurements, units, `approximate`. No invented axes. |
| `gleason_patterns` | gleason patterns | Primary, secondary and optional tertiary pattern, each with an optional percentage. |
| `gleason_score` | gleason score | As today. |
| `grade_group` | coded | Only if stated for this focus. |
| `extraprostatic_extension` | presence | |
| `perineural_invasion` | presence | |
| `histology_type` | coded | Code from `hist_type_sur` (1–7) plus original wording. |

Location values set only their own component and leave the others unknown. Example: `{"type": "location", "laterality": "left", "original_wording": "v levém laloku"}`.

`laterality`, `level`, `zone` and `anteroposterior` are separate observations so each has its own status. The matcher scores them separately.

### Specimen properties

| Property | Value type | Notes |
| --- | --- | --- |
| `classification_pt`, `classification_pn`, `classification_pm` | classification | Original code, edition if stated. |
| `classification_r`, `classification_l`, `classification_v` | classification | As today. |
| `grade_group` | coded | Specimen level. Maps to `isup`. |
| `reported_lesion_count` | quantity | Only an explicit count. |
| `multifocality` | coded | `multifocal` or `unifocal`, only if stated. |
| `histology` | coded | Code from `histol_post_surg` plus original wording. |
| `icd_o` | classification | Only if the report gives the code or wording. |
| `seminal_vesicle_invasion` | presence | Needed for the pT3b check. |

Specimen statements stay on the specimen. Never copy pT, R, L, V or a margin to a focus.

### Other finding properties

`finding_type` (text, for example "zánět"), `laterality`, `level`, `zone`, `textual_location`.

### Issues

Keep `unresolved_attribution` from the current contract: a sentence that could belong to more than one focus gets an issue with the candidate subject IDs and no observation.

## Drawing candidates

Built from `drawing.json`:

1. Each entry in `groups` is one candidate. Each mark in `standalone` is one candidate.
2. Marks in `not_lesion` are not candidates. Their signals go to the details list (see "Issues and flags").
3. For each candidate, derive:
   - its sectors, from axial members, using the sector rule below
   - its patient sides, from the sectors' `patient_side`
   - its side basis, which is `explicit` if every contributing view's `orientation.basis` is `explicit` (a P/L letter) and `inferred` otherwise
   - its levels, from the `level` of every member's sectors, including coronal and sagittal bands
   - its zones and anteroposterior position, from sector zones through the zone table
   - its sector count, the number of sectors that are in

### Sector rule

A sector of a mark is **in** if either of these holds:

- share ≥ 0.15, using the `SectorShare.share` value supplied in `sectors_polygon`
- Gemini named it (`sectors_named`)

A sector listed in `sectors_polygon` or `sectors_cv` that satisfies neither condition is **maybe**. The UI shows maybe sectors unticked.

The central system owns these thresholds in its own versioned rule set. It does not read `extraction.thresholds` from `drawing.json`, because the drawing team may retune theirs for signal purposes.

Do not use `mark.redcap`. It includes every polygon sector at any share.

When CV disagrees with the polygon (`sources_disagree`), the sector stays in and confidence drops.

### Zone table

| Sector zone | Text zone | Anteroposterior |
| --- | --- | --- |
| `pza` | `pz` | anterior |
| `pzpl` | `pz` | posterior |
| `pzpm` | `pz` | posterior |
| `tza` | `tz` | anterior |
| `tzp` | `tz` | posterior |
| `cz` | `cz` | posterior |
| `as` | `as` | anterior |
| `sv` | `sv` | none |

This table is a rule, versioned with the others. Correct it if a pathologist says otherwise.

## Rules brain: matching

The search space is small, so the matcher tries every assignment. The 3 `drawing.json` files have 1, 2 and 4 groups. Report foci are not checked yet.

### Pair score

Score every focus-candidate pair property by property:

| Property | Agree | Conflict | Unknown on either side |
| --- | --- | --- | --- |
| Side | +3 | −3 | 0 |
| Level | +1 per shared level | −1 per text level the candidate lacks | 0 |
| Zone or anteroposterior | +1 for overlap | −1 for contradiction | 0 |
| Size rank | +0.5 if the largest focus by text dimensions pairs with the candidate with the highest sector count | none | 0 |

Size rank is a weak tie-break. Pixels are not millimetres, and the size rank never counts as size agreement.

### Assignment

1. Each focus takes one candidate, or none.
2. A focus may also take one extra standalone candidate on the same side, at −1, for a lesion the drawing pipeline split in two.
3. A candidate belongs to at most one focus.
4. Keep the assignment with the highest total score. Keep the runner-up for the certainty calculation and the review question.

### Matching certainty

| Level | When |
| --- | --- |
| `high` | Best total beats the runner-up by ≥ 3 and side agreement rests on `explicit` side basis. |
| `medium` | Margin ≥ 1, or margin ≥ 3 with `inferred` side basis. |
| `low` | Margin < 1. Raise an `ambiguous_assignment` question showing both assignments, with the best one preselected. |

The weights and margins are starting values in rule set `rules-1`. Tune them on the reference labels (see "Evaluation").

### Leftovers

- A candidate no focus took becomes an `unmatched_candidate` question ("drawing shows ink in pzpl_mid_ls, no text focus there"). It never becomes a lesion.
- A focus that took no candidate stays a lesion, with an `unmatched_focus` question.
- A candidate whose position fits an `other_finding` (same side and level) matches it instead of raising `unmatched_candidate`.

### Memberships

Memberships reference marks, not groups. A candidate from a drawing group records that group as a dependency. If the doctor rejects the group, every membership that depends on it needs reassessment.

## Lesions

1. Each text focus is one lesion.
2. If the report lists no foci but states `multifocality: multifocal` or a `reported_lesion_count`, each candidate becomes one lesion, backed by that statement. Every such lesion gets a `lesion_from_drawing` question.
3. If `reported_lesion_count` differs from the number of lesions, raise `count_mismatch`.
4. A focus spanning both lobes is one lesion with sectors on both sides. Step 5 splits it if the registry wants one instance per side (REDCAP.md open question 2).
5. Lesion order follows text order (A, B, C), with the dominant focus first if the text names one. Order decides the REDCap instance number, because REDCap has no lesion label field.
6. Other findings (zánět) are kept as `other finding` interpretations and do not export until the doctor answers REDCAP.md open question 1.

### Sectors of a lesion

- **Matched**: the union of the in sectors of its candidates' marks. Maybe sectors listed separately.
- **Text only**: if the focus has `laterality`, `level` and `zone` all recorded, propose every sector code with that zone, level and side, with basis `inferred` and an `inferred_sectors` question. Example: PZ, apex, left gives `pza_apex_ls`, `pzpl_apex_ls`, `pzpm_apex_ls`. With side alone, propose nothing.

Codes come from `Other/redcap/sector_crosswalk.csv` by zone, level and patient side.

## Confidence

Use `high`, `medium` and `low`, plus `conflict` for text vs drawing disagreement. Every level has a written explanation. These are qualitative, not probabilities.

### Sector set of a lesion

| Level | When |
| --- | --- |
| `high` | Matching certainty `high`, text side agrees with the drawing side, side basis `explicit`, no "would flag" signal on any member. |
| `medium` | Side agrees but side basis `inferred`, or only mild signals on members (`run_instability` in 2 of 3 runs, `single_source`). |
| `low` | Matching certainty `low`, or `sources_disagree`, `named_vs_polygon` or `group_check_failed` on a member. |
| `conflict` | Text and drawing disagree on side or anteroposterior. Both values stay, with a `side_conflict` or `ap_conflict` question. |

Text-only sector proposals are `low`.

### Text-only fields

Gleason, EPE, PNI, histology, dimensions, pT, R, L and V carry the text extraction certainty and a `single source` tag. The drawing cannot confirm them.

## Issues and flags

### Drawing signals

A drawing signal becomes a doctor issue only if it touches something that reaches the record: a mark in a matched candidate, or a sector on a lesion. Every other signal goes to a collapsed details list.

Adjustments:

- `run_instability` on a mark whose side and level agree with the text drops to `info`.
- `unknown_ink` inside a sector that no lesion has rises to a `question`. It may be a missed lesion.
- Other signals keep their drawing `suggestion`: "would flag" becomes `question`, "info only" and "text is probably right" become `info`.

### Central issue kinds

| Kind | Severity | Raised when |
| --- | --- | --- |
| `side_conflict` | question | Text and drawing sides disagree. |
| `ap_conflict` | question | Text and drawing anteroposterior disagree. |
| `level_conflict` | question | A text level is missing from the matched candidate. |
| `ambiguous_assignment` | question | Matching certainty `low`. |
| `matcher_disagreement` | question | The rules and LLM brains assign differently. |
| `unmatched_candidate` | question | A candidate has no focus. |
| `unmatched_focus` | question | A focus has no candidate. |
| `lesion_from_drawing` | question | Lesion rule 2 applied. |
| `count_mismatch` | question | Reported count differs from the lesion count. |
| `inferred_sectors` | question | Text-only sectors proposed. |
| `check_failed` | info or question | A consistency check failed (see below). |
| `size_note_conflict` | info | A handwritten size disagrees with the text. |
| `llm_missing` | info | The LLM brain did not run. |
| `other` | as given | Free-text issue from the LLM brain. |

Whether a question blocks export is decided in step 5.

## Consistency checks

Checks only raise `check_failed`. They never change a value. Each rule records its source and edition.

| Check | Rule | Severity |
| --- | --- | --- |
| Gleason vs grade group | ISUP 2014: ≤ 6 → GG1, 3+4 → GG2, 4+3 → GG3, 8 → GG4, 9–10 → GG5. Applies per focus and at specimen level. | question |
| pT2c vs sides | pT2c means both lobes. Raise if all lesions and candidates are on one side. | info |
| pT2a or pT2b vs sides | One lobe. Raise if lesions sit on both sides. | info |
| pT3a vs EPE | pT3a goes with EPE present in at least one focus. | info |
| pT3b vs seminal vesicles | pT3b goes with `seminal_vesicle_invasion` present. | info |

Before building, verify each rule against its primary source. AJCC 8th edition, as far as we know, no longer splits pathological pT2, while REDCap still offers pT2a/b/c. Get `COMPARE_TNM_klasifikace.pdf` from the REDCap Surgery C61 page (REDCAP.md section 5) and check the pT rules against it. Until then the pT rules stay `info`.

## Handwritten sizes

The drawing pipeline links size notes to marks (`Mark.linked_to`, `low_trust_note`). When the linked mark belongs to a matched lesion, compare the note's number with the focus's text dimensions:

- Agreement: equal to any text dimension within 2 mm.
- Otherwise: `size_note_conflict`, `info`.

A note never becomes a field value (REDCAP.md section 8).

## LLM brain

The second brain. It runs on every case, in production too.

- Model: Gemini 3.8 Flash. One call per case.
- Input: the report extraction and `drawing.json` as JSON only. No scans. Strip polygons, boxes and pixel data. Keep marks, views, orientations, sectors with shares, patient sides, groups, standalone, not_lesion and signals.
- Output, in the same vocabulary as the rules brain:
  - assignments: focus → candidate marks, with a reason per pair
  - issues: kinds from the table above, or `other` with free text
  - confidence: `high`, `medium`, `low` or `conflict` per lesion property, with a reason
- Record the model ID, prompt SHA-256 and call settings in `combined.json`.
- If the call fails, the rules brain runs alone and `llm_missing` is raised. A failure never blocks the case.

For the hackathon samples the user approved sending this JSON to Gemini on 2026-10-17. Production needs its own decision (AGENTS.md, "Production design").

### Combining the brains

| Item | Rule |
| --- | --- |
| Assignments | The rules brain fills the draft. A different LLM assignment raises `matcher_disagreement` and drops matching certainty to `low`. |
| Issues | Union of both brains. Each issue records which brain raised it. |
| Confidence | The lower of the two levels. Both explanations are kept. `conflict` from either brain wins. |

The two brains read the same inputs. Their agreement is a check on our reading, not a second source, and never counts as corroboration (MATCHING.md rule 10).

A recurring `other` issue from the LLM is a candidate for a new rule.

## `combined.json`

Follows MATCHING.md and ASSESSMENT.md, with support contributions folded into `supports` and `opposes` ID lists. Field names are a draft.

```json
{
  "schema_version": "combined-1",
  "rules_version": "rules-1",
  "created_at": "2026-10-17T12:00:00Z",
  "inputs": {
    "report": {"extraction_id": "...", "sha256": "..."},
    "drawing": {"path": "Other/output/drawing/<case>/drawing.json", "sha256": "...", "git_sha": "..."},
    "decisions": {"sha256": "..."},
    "previous_run": "20261017T113000Z"
  },
  "pairing": {"basis": "supplied association", "certainty": "high"},
  "candidates": [
    {"id": "c1", "source": "group:g1", "marks": ["coronal.m1", "base.m2", "mid.m1"],
     "sectors_in": ["pzpm_base_rs", "pzpl_mid_rs"], "sectors_maybe": ["cz_base_rs"],
     "sides": ["right"], "side_basis": "explicit", "levels": ["base", "mid"]}
  ],
  "matching": {
    "hypotheses": [
      {"id": "h1", "focus": "report:focus-a", "candidates": ["c1"],
       "memberships": [{"subject": "base.m2", "depends_on": ["group:g1"], "certainty": "high"}],
       "score": 7.0, "runner_up_score": 2.0, "certainty": "high", "brain": "rules"}
    ],
    "comparisons": [
      {"hypothesis": "h1", "property": "laterality", "inputs": ["report:obs-12", "base.m2"],
       "outcome": "agreement", "rule": "rules-1/side"}
    ]
  },
  "lesions": [
    {"id": "L1", "order": 1, "kind": "tumour focus", "hypothesis": "h1",
     "sectors": {"in": ["pzpm_base_rs", "pzpl_mid_rs"], "maybe": ["cz_base_rs"], "basis": "inferred",
                 "confidence": {"rules": "high", "llm": "medium", "final": "medium", "explanations": ["..."]}},
     "properties": [
       {"property": "gleason_patterns", "disposition": "adopted", "value": {"...": "..."},
        "supports": ["report:obs-20"], "opposes": [], "tags": ["single source"],
        "confidence": {"final": "high", "explanations": ["..."]}}
     ]}
  ],
  "specimen": {"properties": []},
  "other_findings": [],
  "issues": [
    {"id": "i1", "kind": "side_conflict", "severity": "question", "raised_by": ["rules"],
     "context": ["L1", "base.m2", "report:obs-12"], "alternatives": ["text side", "drawing side"],
     "status": "open"}
  ],
  "details": [],
  "brains": {"rules": {"...": "..."}, "llm": {"model": "gemini-3.8-flash", "prompt_sha256": "...", "raw": {}}},
  "decisions_applied": []
}
```

## Doctor decisions and re-runs

The UI saves the doctor's changes in `decisions.json`. Each entry has an ID, a kind (for example `assign_mark`, `reject_membership`, `set_value`, `resolve_issue`), its target, the new value, the reviewer, a timestamp and a reason.

A re-run after a decision:

1. Loads the previous `combined.json` and `decisions.json`. If the report or drawing hash differs from the previous run's pinned inputs, it does a fresh run instead (MATCHING.md asks for a new attempt when inputs change) and re-applies only the decisions whose targets still exist. Decisions whose targets are gone become `info` issues.
2. Keeps every assignment from the previous run fixed, except the ones a decision changes.
3. Applies the decisions.
4. Recomputes the values derived from assignments: sectors, confidence, comparisons, checks and issues.
5. Does not call the LLM. The LLM's earlier output stays, marked `before_decisions`.
6. For anything a decision touched, drops the LLM from the combination: confidence uses the rules level only, and the decision resolves any `matcher_disagreement` on that target. The stale LLM opinion stays visible but no longer counts.
7. Writes a new run folder.

Derived values are pure functions of the fixed assignments, so a lesion the doctor did not touch comes out unchanged. Nothing moves unless the doctor moved it.

How the UI triggers a re-run is step 5 work.

## Step 5 constraints

The projection from `combined.json` to the REDCap CSV is deferred. It will be deterministic: `combined.json` goes into the review state that `review-ui/redcap.js` reads, and `buildLesionCsv` writes the CSV, so the project has one CSV writer. To keep that easy:

- Keep full schema statuses in `combined.json`. The projection maps them using REDCAP.md section 7.
- Keep REDCap sector codes from `sector_crosswalk.csv` as the sector identifiers.
- Keep lesion `order` stable across re-runs.
- Mark inferred values so the projection can hold them until the doctor accepts them.

## Evaluation

There is no expert ground truth and no doctor to label matches. For the 3 cases with `drawing.json` (d7783a97, 33f35325, cfc80c0f):

1. Claude reads the report scans and writes the `report-2` extraction for each case. The user approved this for the hackathon samples on 2026-10-17.
2. Claude writes non-expert reference labels: focus-to-mark matches and the sector set per lesion. Uncertain labels are marked uncertain.
3. Each brain is scored against the labels: correct assignment per focus, and sector set overlap per lesion (Jaccard).
4. Count issues per brain and per kind, and the cases where only one brain raised an issue.
5. The user also checks by eye.

Three cases make a probe. Report the numbers as a probe. The `report-2` inputs are hand-written by the same reader who writes the labels, so they are cleaner than real extractor output, and the scores will flatter both brains. Store the labels and scores under `Other/output/central-eval/`.

## Code layout

| File | Job |
| --- | --- |
| `central/rules.py` | Versioned weights, thresholds and tables (`rules-1`). |
| `central/inputs.py` | Load and validate `report-2` and `drawing-1`. Pin hashes. |
| `central/candidates.py` | Candidates, sector rule, zone table. |
| `central/matching.py` | Pair scores, assignment search, matching certainty. |
| `central/lesions.py` | Lesions, sectors, text-only sectors. |
| `central/confidence.py` | Confidence tables. |
| `central/issues.py` | Signal filtering and central issue kinds. |
| `central/checks.py` | Consistency checks. |
| `central/llm.py` | LLM brain call and output validation. |
| `central/combine.py` | Combining the two brains. |
| `central/decisions.py` | Decisions and re-runs. |
| `central/output.py` | `combined.json` models and writing. |
| `central/cli.py` | `python -m central <case>`. |

Import `report_extractor.models` for shared vocabulary. Do not import `drawing_pipeline`: validate `drawing.json` against our own copy of the `drawing-1` contract, and ask the drawing team to bump the version when the format changes.

## Build order

1. Write the 3 `report-2` extractions and the reference labels.
2. `inputs.py` with validation on the 3 cases.
3. Candidates and the sector rule. Compare sector sets against the labels.
4. Rules brain matching. Score against the labels.
5. Lesions, confidence, issues, checks. Write `combined.json`.
6. LLM brain, then combining.
7. Evaluation on the 3 cases.
8. Decisions and re-runs.
9. Step 5 projection, later.

## Open questions

- Registry: benign findings as lesion instances, and one instance per focus or per side (REDCAP.md section 11, questions 1 and 2).
- pT rules: verify against `COMPARE_TNM_klasifikace.pdf`.
