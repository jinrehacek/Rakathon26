# Image pipeline spec

Written 2026-10-17. This is the final plan for the drawing pipeline. It replaces [IMAGE-PIPELINE-RECONCILIATION.md](IMAGE-PIPELINE-RECONCILIATION.md) and [IMAGE-IMPLEMENTATION-PLAN.md](IMAGE-IMPLEMENTATION-PLAN.md). Where they differ, this file wins.

Output follows [STRUCTURE.md](../data_schema/STRUCTURE.md) and, for groups, [MATCHING.md](../data_schema/MATCHING.md).

## Goal

Get as much as we can out of the drawing. The drawing pipeline does not read the report.

1. Find every bubble and other mark in every view.
2. Group the bubbles into predicted lesions.
3. Send everything to the central system, including what we are unsure of.

The central system reads our output and the text extraction. It matches drawing and text, decides, and raises flags for the doctor. We never raise a flag. We send data, **signals** (a reason something may be wrong) and a **suggestion** per signal, for example "would flag" or "text is probably right". Pathologists usually put more care into the text than the drawing, so where the two disagree our default suggestion favours the text.

## Terms

| Term | Meaning |
| --- | --- |
| View | One printed panel: coronal, sagittal, seminal vesicles (SV), base, mid, apex, urethra. A diagram view subject in STRUCTURE.md. |
| Mark | Any non-template ink Gemini reports: bubble, open arc, small circle, shading, side letter, text, arrow, other. A diagram mark subject. Never a lesion. |
| Bubble | A mark that outlines an area: closed outline, open arc, small circle or shading. |
| Group | A predicted lesion: two or more marks the grouping step thinks show one finding. A within-document matching hypothesis in MATCHING.md. |
| Signal | A machine-readable reason for doubt, sent to the central system. Not a flag. |
| Reference coordinates | Pixels of the 1342 × 1737 reference template that every scan is aligned to. |
| Cleaned image | The aligned scan with the printed template subtracted, so only ink remains. |
| CV | The OpenCV route: ink mask, connected components, loop fill, pixel counts per sector. |

## Two independent machines

Gemini and CV run separately. Neither sees the other's output. Gemini never gets CV components, numbers or fills. A comparison step runs after both finish.

Gemini has priority when nothing else decides. We build both, grade both, and decide priority from the grades.

Both machines read the same cleaned image. If subtraction loses faint pencil, both miss it and still agree. "No signal" means the two machines agree. It does not mean the ink extraction caught everything. The original colour crop in the Gemini call is the only guard against lost ink.

## Flow

```
scan
 └─ preprocess: align → subtract → cleaned image + ink mask      (exists; add hysteresis)
     ├─ Gemini: per view, 3 sampled runs → merge runs → marks
     │           └─ sectors (a) named by Gemini, (b) polygon on sector map
     └─ CV: components → fill → sectors (c)
 └─ compare: pair Gemini bubbles with CV regions → signals
 └─ orientation per view → patient side → REDCap codes
 └─ grouping: one LLM call per case → groups → code checks → signals
 └─ drawing.json
```

## Preprocess

Exists in `scripts/extract_handwriting.py`: ORB + RANSAC alignment, template subtraction, `mask.png` and crops per view in reference coordinates.

Add a **hysteresis threshold** to the ink mask. Strong ink pixels seed the mask, and weak pixels join only if they connect to a seed. This targets faint pencil loops that break into dashes. Both machines benefit because both read the cleaned image.

## Views and orientation

Every view has a fixed **symmetry axis** in reference coordinates, defined once by hand. It is not detected per sheet.

The view's coordinate convention (the STRUCTURE.md *Diagram view* attribute) is: origin on the symmetry axis, x grows to the viewer's right, y grows down, units are reference pixels. Sagittal has no left/right, so its convention uses anterior/posterior instead.

Orientation is an observation on the view subject. STRUCTURE.md lines 50, 149 and 198 already allow this, so the schema needs no new field. The value says which sign of x is patient right. To flip a view, change that one sign. Mark coordinates never change.

| Evidence | Basis | Rule |
| --- | --- | --- |
| Side letter in or next to the view | explicit | P or R = right, L = left. The letter's side is the sign of x at its centre. Gemini reads the letter; code decides the side. |
| Letter between SV and Base | explicit | Applies to the whole axial block: SV, base, mid, apex. |
| Unlettered axial view, another axial view lettered | inferred | Takes that view's orientation. |
| Unlettered axial view, no axial letters | inferred | Default: patient right on viewer-left. |
| Unlettered coronal view | inferred, certainty low | Default: patient right on viewer-left. |
| Letter in the sagittal view | none | Signal `letter_in_sagittal`. P may mean posterior. |
| Two letters on one view that disagree | none | Keep both letter observations, orientation `unknown`, signal `letter_conflict`. |

The report never sets orientation. The central system compares sides with the text.

A letter belongs to the view whose crop, plus a margin, contains it.

Survey behind the defaults (2026-10-17, one agent looking at all 40 sheets by eye, a probe): axial letters were standard on all 30 sheets that had them. Coronal views could be judged on 14 sheets, and 11 of those were standard (79%). Sheets 0002 and 0027 have coronal letters opposite to their axial letters. No R appeared, only P and L.

### Patient side and REDCap codes

- A sector contact is stored as zone + level + **image side**.
- **Patient side** = image side combined with the view's orientation. Basis `inferred`, derived from both observations.
- The REDCap code is looked up from zone + level + patient side in `Other/redcap/sector_crosswalk.csv`. Never read it from the `drawn_on_viewer` column alone. The old `redcap_if_standard_orientation` field is dropped.

## Sector maps

- **SV, axial and urethra views:** the 41 ctsit polygons in `Other/reference/sectors.json`, with REDCap codes. SV is included. `sector_regions.py` skips it today.
- **Coronal and sagittal views:** 12 new regions drawn once on the reference. Coronal: 3 levels (base, mid, apex, from the printed dashed lines) × 2 image sides. Sagittal: 3 levels × anterior/posterior. They give level extent, side (coronal) and front/back (sagittal). No REDCap codes. Gemini sees them on its map and code uses them. The doctor's UI does not show them.

## Gemini

Model `gemini-3.8-flash`, sampled with temperature 1.0 (`probe_gemini.py` already uses it) and no response caching, so the 3 runs differ. This replaces the old pass A and pass B. Change the prompt (`prompts/gemini_drawing.md`) and the schema in `scripts/probe_gemini.py` to match.

Every call on a scan needs the user's go-ahead in that session (AGENTS.md).

**Input per view, one request:**

1. The original colour crop.
2. The cleaned crop over the coloured sector map, with zone labels as printed. No short codes, no CV numbering.

The prompt tells Gemini to trust the cleaned image for geometry and to use the original to catch ink the cleaning lost.

**Output per mark:**

| Field | Notes |
| --- | --- |
| `kind` | bubble kinds (closed outline, open arc, small circle, shading), side letter, text, arrow, other |
| `polygon` | On the cleaned crop. Code maps it to reference coordinates. |
| `box_2d` | Kept as a fallback for marks too thin for a polygon. |
| `text` | Transcription of handwriting, if any. |
| `sectors` | Zone + level + image side, named by Gemini. Sector source (a). |

No self-reported certainty. It said "high" on everything in the probes.

### Merging the 3 runs

- Match marks across runs by polygon IoU ≥ 0.5.
- In 3 of 3 runs: normal mark. In 2 or 1 of 3: kept, signal `run_instability` with the count.
- Keep the polygon that overlaps the other runs best.
- Keep each run's sector list. A sector named in only some runs gets a `run_instability` signal.
- Merged marks get stable IDs: `<view>.m<n>`, for example `base.m2`.

### Sectors from Gemini

- **(a) Named:** the merged named sector lists.
- **(b) Polygon:** code rasterises the merged polygon on the sector label image and counts pixels per sector. Basis `calculated`, derived from the Gemini polygon.

Signal `named_vs_polygon` when Gemini names a sector its polygon does not touch, or omits a sector holding ≥ 15% of its polygon's area.

## CV

`scripts/sector_regions.py`, extended to SV and the 12 longitudinal regions:

- connected components of the ink mask
- closed loops filled
- gappy loops closed by growing ink up to 10 px, with the bridged stretch recorded
- open strokes and shading not filled
- pixels counted per sector

This is sector source (c). CV does not label mark kinds.

## Compare

Runs after Gemini and CV. Neither machine sees its output.

1. **Pairing.** Rasterise each merged Gemini bubble polygon in reference coordinates. A CV region pairs with a bubble when ≥ 50% of the region's pixels fall inside the polygon. One bubble may pair with several CV regions (a split loop).
2. **Sector agreement**, only for bubbles paired with a closed or bridged CV region. Compare the share of the bubble's area per sector in (b) and (c). Signal `sources_disagree` when any sector differs by ≥ 15 percentage points. Smaller differences are recorded without a signal.
3. **Single source.** Bubbles with no closed or bridged CV pair get `single_source`. Open arcs, shading and faint pencil usually land here. Suggestion: "info only". These should not reach the doctor's queue by default.
4. **Unknown ink.** A CV component above `minimum_component_pixels` with < 50% of its pixels inside any merged Gemini mark (polygon grown by 10 px) becomes a mark of kind `unknown ink` with signal `unknown_ink`.
5. **Not in ink.** A Gemini bubble with no ink-mask pixels under its polygon gets `not_in_ink`. Either Gemini invented it or subtraction lost faint ink. The count also shows whether hysteresis helps.

The 50%, 15% and 10 px values are starting guesses. Grading sets them once.

## Notes and handwriting

We do not mine size or free text into structured fields. Every Gemini transcription ("cca 25mm", "zánět", "vlevo?") stays in the output as a text mark with basis `explicit`, extraction certainty `low`, and signal `low_trust_note`. Code links it to the nearest mark (`inferred`). The central system decides what it means. "zánět" (inflammation) matters most here, because it keeps that outline out of the tumour groups.

## Grouping

One LLM call per case, Gemini 3.8 Flash. It never sees the report.

**Input:**

- the full original sheet
- the full cleaned sheet with every merged mark's polygon drawn and labelled with its ID
- the merged per-view JSON: marks, sectors, levels, patient sides, orientation per view, notes

**Output:**

- `groups`: `{id, members: [mark IDs], proposed_finding_kind: tumour | other | unresolved, reason}`. Two or more members, as MATCHING.md requires for a hypothesis.
- `standalone`: marks that look like a lesion drawn in one view only, with a reason.
- `not_lesion`: marks judged to be letters, text, arrows or noise, with a reason.

**Code checks per group.** A failed check adds signal `group_check_failed` with the reason.

- All members have one patient side, or the group is labelled bilateral.
- Axial levels covered match the coronal and sagittal level bands of the members.
- No mark is in two groups.
- When only a coronal member breaks the side check, the signal is `coronal_maybe_mirrored` instead.

**Recompute.** The app owns re-running groups after a doctor edit. Our part: mark IDs stay stable, groups only point at marks and never merge them, and the grouping call accepts an optional list of fixed groups it must keep unchanged.

## Signals

Each signal sets `review_status: needs review` on the affected observations and writes the reason into `certainty.explanation`. `drawing.json` also ends with a `signals` list as a quick index.

| Kind | Raised by | Default suggestion |
| --- | --- | --- |
| `sources_disagree` | compare | would flag |
| `named_vs_polygon` | Gemini sectors | would flag |
| `run_instability` | merge | would flag if 1 of 3, info if 2 of 3 |
| `single_source` | compare | info only |
| `unknown_ink` | compare | would flag |
| `not_in_ink` | compare | would flag |
| `group_check_failed` | grouping checks | would flag |
| `coronal_maybe_mirrored` | grouping checks | info only |
| `letter_conflict`, `letter_in_sagittal` | orientation | would flag |
| `low_trust_note` | notes | text is probably right |

## Output: `drawing.json`

One file per case, keyed by the case ID from the preprocess `manifest.json`, written under `Other/output/` (ignored). It uses the same pydantic models as `report_extractor/models.py` on `main` (`Subject`, `Evidence`, `Certainty`, `ReviewStatus` and others), extended with image geometry. Two outputs on two different models would be the first thing to break when the central system combines them.

Sections: `extraction` (git SHA, model ID, prompt hash, thresholds, timestamp), `views`, `marks`, `groups`, `standalone`, `not_lesion`, `signals`.

```json
{
  "views": [
    {"id": "base", "kind": "diagram view", "level": "base",
     "coordinate_convention": {"origin": "symmetry axis", "axis_x_ref": 671, "x": "viewer right", "y": "down", "units": "reference px"},
     "orientation": {"status": "recorded", "value": "patient right at x<0", "basis": "explicit",
                     "evidence": ["base.m5"], "review_status": "unreviewed",
                     "certainty": {"extraction": "unassessed", "interpretation": "unassessed"}}}
  ],
  "marks": [
    {"id": "base.m2", "view": "base", "kind": "closed outline", "runs_found": 3,
     "polygon_ref": [[512, 1033], [530, 1001], "..."],
     "sectors": {
       "named":   [{"zone": "pzpm", "level": "base", "image_side": "left"}],
       "polygon": [{"zone": "pzpm", "level": "base", "image_side": "left", "share": 0.71},
                   {"zone": "cz",   "level": "base", "image_side": "left", "share": 0.29}],
       "cv":      [{"zone": "pzpm", "level": "base", "image_side": "left", "share": 0.64},
                   {"zone": "cz",   "level": "base", "image_side": "left", "share": 0.36}]},
     "patient_side": {"value": "right", "basis": "inferred", "derived_from": ["base.orientation"]},
     "redcap": ["pzpm_base_rs", "cz_base_rs"],
     "review_status": "unreviewed"},
    {"id": "sagittal.m3", "view": "sagittal", "kind": "text", "text": "cca 25mm",
     "basis": "explicit", "certainty": {"extraction": "low", "interpretation": "unassessed"},
     "linked_to": {"mark": "sagittal.m1", "basis": "inferred"}}
  ],
  "groups": [
    {"id": "g1", "members": ["coronal.m1", "base.m2", "mid.m1", "apex.m2"],
     "proposed_finding_kind": "tumour", "reason": "right posterior PZ, base to apex, matches coronal extent",
     "review_status": "unreviewed", "matching_certainty": "unassessed"}
  ],
  "signals": [
    {"kind": "low_trust_note", "observations": ["sagittal.m3"], "reason": "handwritten size, read by Gemini only",
     "suggestion": "text is probably right"}
  ]
}
```

Field names are a draft. Agree them with the central-system side before step 4 of the build order.

## Build order

The first four steps give a working end-to-end slice on one case. Then widen.

1. **Gemini v2.** New prompt and schema, both images per view, all 6 views, the reference map with the 12 longitudinal regions, 3 runs, merge.
2. **Sides.** Symmetry axes, orientation rules, patient side, polygon sectors (b), REDCap codes.
3. **Grouping.** The call plus code checks.
4. **`drawing.json`** with signals, on one case end to end.
5. **CV.** Hysteresis, SV and longitudinal regions in `sector_regions.py`, the compare step.
6. **Grading round 1** (below).
7. **Hand-off.** The central system reads a real `drawing.json`.

## Testing

AGENTS.md: before calling an image-pipeline change good, the agent prepares 5 to 8 grading sheets and the user grades them.

**Grading sheet**, one per view:

1. original colour crop
2. cleaned crop with merged Gemini polygons and mark IDs
3. CV fill over the sector map
4. table per bubble: sectors from (a), (b) and (c), the signals

**Grader writes**, per bubble and **per source**: `ok`, `extra <sector>`, `missing <sector>`. Per bubble: `wrong kind` or `not a mark`. Per view: marks nobody found, and orientation right or wrong. Per case, per group: `right`, `split <marks>`, `merge with <group>`. The per-source verdicts are what decide priority between (a), (b) and (c).

Grades are saved to `Other/output/grading/round-<n>.md` (ignored), with counts in `Other/research/sector_grading.md`. The last comparison page only copied grades to the clipboard and they were lost, so the grading page must write a file.

Each round is a probe. Report counts, not accuracy.

## Numbers we have

All are probes.

| Number | Source |
| --- | --- |
| Gemini 3.8 polygons on the cleaned image: median per-contour distance to CV ink 0.95 px (43 contours). Flash-Lite: 13.37 px. | `Other/output/gemini-probe/eight-crop-comparison/polygon_review.json` |
| Panel-level sector sets on 14 axial views: CV vs Gemini pass B 6/14 agree, CV vs pass A 7/14, pass A vs pass B 8/14. Not per mark. Not recomputed. | `Other/output/sector-comparison/index.html` |
| CV vs Gemini grades | None saved. The user's informal impression is that CV did a bit worse. |
| Coronal orientation 11/14 standard; axial letters 30/30 standard | Agent survey of 40 sheets, 2026-10-17 |

## Backlog

Only if the plan above runs into trouble.

- Run grouping 3 times and signal groups that change between runs.
- Open-weight models, mainly for self-hosting in production, since none is likely to beat Gemini 3.8 Flash here: Moondream 3.1 `segment` (returns an SVG outline; check the licence first) and Qwen3.6-27B (boxes and points, Apache-2.0).

## Dropped

- Pass A / pass B split, and Set-of-Mark numbered CV components in Gemini's input. They break independence.
- Short sector codes printed in the image.
- Arrow ray-casting for size links. Hole counting for P vs L.
- Model self-reported certainty. Gemini Flash-Lite. SAM as a sector source. Detecting a mirrored view from printed template landmarks (the print never changes). TrOCR for letters.
- Pixel-based size, and structured size or free text from the drawing. Size comes from the report.
- `redcap_if_standard_orientation`.

## Production note

The user says Google can arrange zero data retention for Gemini. Confirm the retention and no-training terms for the exact service, model and features before production, as TASK.md requires.
