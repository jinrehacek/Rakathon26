# Image pipeline reconciliation

Written 2026-10-17. This file compares [IMAGE-IMPLEMENTATION-PLAN.md](IMAGE-IMPLEMENTATION-PLAN.md) with what the OpenCV and Gemini probes actually showed, and sets the next steps. For plan steps 5 to 7 this file wins where the two differ. Here "reconciliation" means fixing the plan. It is not schema step 4 in [ASSESSMENT.md](../data_schema/ASSESSMENT.md).

Output must follow [STRUCTURE.md](../data_schema/STRUCTURE.md).

## What we already have

| Piece | State | Source |
| --- | --- | --- |
| 41 sector polygons on our reference | The ctsit polygons (513 × 631) are mapped onto our 1342 × 1737 reference with a SIFT + RANSAC homography: 369 of 427 matches kept, 0.38 px median feature error. It's a fitted transform, not a plain upscale. The upstream polygons are hand-drawn and coarse, so a contact a few pixels from a printed line is uncertain. | `Other/reference/sectors.json`, [reference_geometry_implementation.md](research/reference_geometry_implementation.md) |
| REDCap codes for those polygons | Every ctsit key maps to its `sur_prostate_regions` code, checked against the live form. Each code has `drawn_on_viewer`: axial patient right is drawn on the viewer's left. | `Other/redcap/sector_crosswalk.csv` on `main`. This branch needs `main` merged in. |
| Page alignment | ORB + RANSAC. All 8 probe sheets pass. Scan 7 has about 1 px median residual in every panel. | `scripts/extract_handwriting.py`, per-sheet `metadata.json` |
| Ink mask per crop | `mask.png` in reference coordinates. So every ink pixel can look up the sector it sits in. | `Other/output/handwriting/scan_*/<view>/` |

So we already have the template, the black ink and the sector of every pixel. What we don't have yet is a way to turn ink into marks and marks into areas.

## The big question: ink to sectors

**Answer: code does the geometry and the sector maths. The model says what each stroke is.**

| | Gemini only (what the probe did) | Code only | Combined (do this) |
| --- | --- | --- | --- |
| Where the mark is | Model traces 8 to 40 points | CV mask, exact pixels | CV mask |
| Which sectors | Model names them | Fill closed loops, count pixels per sector | Code, from the mask |
| Is it an outline, arrow, text, P/L letter or noise | Model | Rules: closed or not, inside the organ or not, size | Model labels numbered strokes. Rules are the fallback. |
| Handwriting ("zánět", "22 mm", P, L) | Model | Can't | Model |
| Ink the CV missed (faint pencil) | Model, pass A | Can't | Model, pass A, becomes a doctor question |
| Seen in the probe | 3.8 pass A drew polygons over nothing on scan 7 Base. Every mark says certainty "high". | Clean loops are trivial. Pencil shading falls apart. | |

Why we had Gemini polygons at all: the plan called them an optional experiment ("Exact VLM polygons are optional"). The experiment answered the question. On the cleaned image, 3.8 traced close to the ink. On the original image it sometimes traced nothing real. The mask already has the exact shape, so the model's polygon adds nothing for sector work. Drop polygons from both passes. Pass A keeps `box_2d` so code can check whether a mark it found has any CV ink inside it.

Self-reported certainty goes too. It says "high" on everything, so no decision can use it.

Flash-Lite is out. It missed obvious marks on scan 7 Base.

### What I looked at

- Scan 7 Base `mask.png`: the AFS oval, the TZ circle and the PZpl loop are clean closed loops. Filling them is easy. The faint pencil outline behind them is broken dashes, so the code will miss it, and pass A has to catch it.
- Scan 13 Apex: the pencil shading over AFS and TZa comes out as specks in the mask. The code can't fill that. It's a doctor question.

That's two crops, so treat it as a probe. Round 1 below is the real check.

## How the code part works

All in reference coordinates, per axial crop.

1. **Sector label image.** Rasterise the 41 polygons once into a label image. Pixel value = ctsit key, 0 = outside. Join the key to `sector_crosswalk.csv`. The polygons are hand-drawn, so check for gaps between neighbours and pixels claimed by two sectors. Ink inside an organ gap is a question, not lost. A double-claimed pixel counts for both sectors and is flagged.
2. **Components.** Connected components of `mask.png`. Number them c1, c2 and so on. Save a coloured, numbered image.
3. **Closed loop.** A component that encloses a hole bigger than `H` px is a closed outline. Its region = the filled outer contour.
4. **Broken loop.** In an analysis copy only, grow the ink by r px (3, 6, then 10) until the loop encloses something, then shrink the hole back by r. That closes gaps up to about 2r px. Joining loose ends one pair at a time was tried first and failed: dash fragments and text inside an outline stole the pairings. The boundary stretch with no ink under it is drawn red, the region is labelled "bridged", and it becomes a doctor question. At 15 px an arrow plus text closed into a fake loop (scan 12 Apex), so the cap is 10. The display layer stays untouched, as the plan requires.
5. **Everything else gets no fill.** That covers open arcs, shading, arrows and text. An open arc lists the sectors its stroke crosses as stroke-only contacts, plus a question.
6. **Overlap.** For each region, count pixels per sector. Save the interior pixel count, the stroke-only pixel count and the fraction of the sector covered. Keep every nonzero sector. Contacts below `S` px become questions, not deletions.
7. **Fallback rules for kind.** A component entirely outside the organ outline is probably an annotation, such as P/L, a note or a size. Only specks below `minimum_component_pixels` count as noise. Small circles inside the organ are real marks: scan 7 Base has one in image-right PZpl, and scan 14 Mid has two in TZa. A component that neither the rules nor the model can label stays a candidate mark and becomes a question. These are proposals; the model label wins if present.

`H`, `G` and `S` start as guesses. Grading tunes them once. They go into the extraction metadata.

Coronal and sagittal views don't show the axial grid. They give level and extent only. The seminal-vesicle panel can give `sv_base_*` codes the same way as the axial views.

## What the model does

Model `gemini-3.8-flash`, one view per request, as before.

- **Pass B** gets the black-layer crop on the colour sector map, with each component drawn in its own colour and its number next to it. It returns, per number: kind (outline, open arc, shading, arrow, measurement, text, P/L letter, noise), the text if any, and which numbers belong to one mark (a loop split into c3 + c4). It also gives a sector list per mark as a second opinion, using zone names and image side. It returns no coordinates and no certainty.
- **Pass A** stays independent. It gets only the original colour crop, with no numbers. It returns marks with `box_2d`, kind and text. Code then checks every A box. If an A mark has no component inside its box, the result is the question "CV missed this, is it a mark?".

Both are a prompt and schema change to the existing `scripts/probe_gemini.py` and `prompts/gemini_drawing.md`, not a new runner.

## Output per case

One `drawing.json` per case, keyed by the case ID from Matěj's preprocess `manifest.json`. It uses STRUCTURE.md concepts:

- **Extraction:** script git SHA, model ID, prompt hash, `H` / `G` / `S` values, timestamp.
- **Subjects:** one per view, and one per mark contained in its view. A mark is a diagram mark, never a lesion.
- **Observations per mark:**
  - kind: basis `inferred`, from the model or a rule (say which).
  - geometry: basis `calculated`. Component IDs, plus the filled-region mask path, in view coordinates.
  - handwriting: basis `explicit`, or status `unreadable`.
  - sectors: basis `calculated`. A Location value with level, zone, image side, contact type and pixel counts.
  - anatomical side and REDCap code: basis `inferred`, under the assumption "axial viewer-left = patient right". It points to the `sector_crosswalk.csv` row. A handwritten P or L in the same view is linked as supporting evidence, because the letter is the drawing's own side witness. Matching compares this with the report's side and raises a conflict if they differ. The report still decides.
  - model sectors: basis `inferred`, kept separate from the calculated ones.
- **Evidence:** page-coordinate box, crop paths and the numbered image.
- **Certainty and review:** every observation gets the schema's one certainty block, `unassessed` because model self-ratings are dropped, plus a review status. Bridged loops, open arcs, small contacts, A-only marks, model-vs-calculated sector disagreements and shading set the affected observation to `needs review`, with the reason in the certainty explanation.
- **Issue list (outside the schema):** a per-case list that points at those `needs review` observations, so the review screen can show a queue. It's a convenience index, not schema data.

Example of one mark:

```json
{
  "id": "base.m2", "view": "base", "components": ["c4"],
  "kind": {"status": "recorded", "value": "outline", "basis": "inferred", "by": "model_B",
           "certainty": {"extraction": "unassessed", "interpretation": "unassessed"}, "review_status": "unreviewed"},
  "region": {"closed": true, "bridged": false, "mask": "base/region_m2.png"},
  "sectors": [
    {"level": "base", "zone": "tza", "image_side": "left", "contact": "interior", "px": 4210, "basis": "calculated",
     "redcap_if_standard_orientation": "tza_base_rs"},
    {"level": "base", "zone": "tzp", "image_side": "left", "contact": "interior", "px": 1380, "basis": "calculated",
     "redcap_if_standard_orientation": "tzp_base_rs"}
  ],
  "sectors_review": {"review_status": "needs review",
                     "certainty": {"extraction": "unassessed", "interpretation": "unassessed",
                                   "explanation": "model omits TZp, code has 1380 px interior"}},
  "model_sectors": [{"level": "base", "zone": "tza", "image_side": "left", "basis": "inferred"}]
}
```

The other contributor's matching PR consumes this. Agree the field names with them before step 6.

## Testing: the user grades, the agent prepares

The user is happy to look at 5 to 8 results per round and say which are right. That is the accuracy check for this pipeline. There is no labelled benchmark.

**Grading sheet**, one per crop, four panels side by side:

1. original colour crop
2. numbered components
3. filled regions over the colour sector map
4. table: mark → kind, text, calculated sectors, model sectors, issues

**What the grader writes**, per mark: `ok`, `extra <sector>`, `missing <sector>`, `wrong kind`, or `not a mark`. Per crop, add any mark nobody found. Grades go to `Other/output/grading/round-<n>.md` (ignored). Counts go to `Other/research/sector_grading.md`.

| Round | Input | Model calls | Answers |
| --- | --- | --- | --- |
| 1 | The 8 existing crops | none, code only | Does the CV mask + fill + overlap give the right sectors on its own? |
| 2 | 8 views from Matěj's preprocess batch, cases not used in round 1 | Gemini 3.8, A + B | Does the combined route hold on new sheets? |
| 3, if time | All 37 cases, grade a random 8 | Gemini 3.8 | Same, wider |

Rounds 2 and 3 need the user's Gemini go-ahead in that session (AGENTS.md).

If round 1 shows wrong sectors on clean closed loops, suspect the coarse ctsit polygons before the mask. The fix then is zone masks from the flat colours of our reference image, and only then.

Each round is a probe. Report counts, not accuracy.

## Steps

Each step ends when its "done" holds.

0. **Housekeeping.** Merge `origin/main` into this branch to get `Other/redcap/` and `preprocess/`. Expect a conflict on `README.md`: `main` renamed it and PR #3 edits it. Move both `build_viewer.py` files out of `Other/output/` into `scripts/` and commit them, so future numbers can be rebuilt from the repo. The existing 32 readings came from an older `probe_gemini.py` and stay unreproducible. Round 2 replaces them. *Done:* both viewers run from `scripts/`, and the branch contains `sector_crosswalk.csv`.
1. **Sector label image.** *Done:* a label PNG plus an overlay on the colour reference, checked by eye. Every key has a crosswalk row.
2. **Components, fill and overlap** as described above. *Done:* each of the 8 crops has a JSON listing components, closed / bridged / open status and per-sector pixel counts.
3. **Round 1 grading.** Build the sheets and the user grades them. *Done:* `round-1.md` filled in, thresholds set once from it.
4. **Prompt v2.** Pass B gets numbered components, and pass A stays independent. Remove polygons and certainty from both. *Done:* a dry run validates against the new schema and the tests pass.
5. **Case runner.** Preprocess batch folder in; out come `drawing.json`, crops and grading sheets per case. Check that Matěj's masked-ID box doesn't appear as ink. *Done:* one case runs end to end.
6. **Round 2 grading** on Matěj's batch, after the Gemini go-ahead. *Done:* `round-2.md` filled in, with counts in `sector_grading.md`.
7. **Hand-off and PR blockers.** Agree the JSON with the matching contributor. Fix review items 1, 2 and 12 from PR #3, and update the superseded lines in IMAGE-IMPLEMENTATION-PLAN.md. *Done:* the matching contributor can read a real `drawing.json`.

## Dropped

- Gemini polygons as a source for sector contact.
- Model self-reported certainty.
- Gemini 3.5 Flash-Lite.
- SIFT and ECC fallbacks, unless an alignment fails.
- Better subtraction. It's good enough for now. Round 1 shows whether it's the limit.

## Still open

- Values for `H`, `G` and `S`.
- Pencil shading (scan 13). For now it's a question. Revisit if grading shows it's common.
- Whether a cheaper model can do pass B once its job is only labelling numbered strokes. Not in this plan.
