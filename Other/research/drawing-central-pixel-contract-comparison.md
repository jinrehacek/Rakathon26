# Drawing and central pixel contract comparison

Inspected 2026-10-17. Drawing PR [#11](https://github.com/jinrehacek/Rakathon26/pull/11), clean local head `e5b5424335afcb1ae0f6f3f541560198f92c4562`. Compared with the untracked `Other/CENTRAL-SPEC.md` in the main worktree. This is a source review and local geometric probe, not a model accuracy evaluation.

## Recommendation

Keep geometry calculations in the drawing producer and final sector selection in central. Adding a sector-area denominator fits that division. Adopting `coverage >= 0.5` is a separate policy decision that has no demonstrated benefit on the three available outputs. Ship the existing contract first, retain all contacts, and grade the differences before enabling another automatic inclusion rule.

Drawing already exports pixels. The useful objection is to treating an arbitrary geometric threshold as reliable anatomical evidence, or duplicating geometry processing in central. The drawing spec explicitly sends measurements and signals to central for decisions. The authoritative schema permits calculated geometry but forbids inventing physical scale. [Drawing goals][drawing-goals], [schema rules][schema].

## Verified semantics

For mark mask `M` and the raster label assigned to sector `S`:

| Quantity | Actual meaning |
| --- | --- |
| `px` | Count of mask pixels assigned to this sector. |
| `share` | `px / sum(px across sectors touched by M)`. Off-map pixels do not enter the denominator. |
| Proposed `sector_px` | Count of all pixels assigned to the sector in the same label image. |
| Proposed coverage | `px / sector_px`, the fraction of a schematic sector covered by this mask. |

`sector_shares` performs these counts on crop-sized masks in the aligned 1342 by 1737 reference frame and rounds share to four decimals. Adding the crop origin changes position, not pixel area. `label_image` paints sector polygons sequentially; later polygons own shared raster pixels. Therefore calculate `sector_px` from the final label image, not from vector polygon area or independently filled polygons. [Reference implementation][reference].

The mask's meaning also matters. Closed polygons are filled. Open polylines use an arbitrary six-pixel stroke. CV loops count interiors and nearby outline ink; CV shading and open strokes count ink only. A coverage value for an open arc is therefore stroke coverage, not inferred enclosed area. Neither coverage nor share measures tumour volume, millimetres, or confidence. [Raster implementation][geometry], [CV mask implementation][cv].

There are three different 15% quantities in the current proposal:

- Drawing `named_vs_polygon` tests intersection divided by the **whole rasterised mark**, including pixels outside all sectors.
- Drawing `sources_disagree` tests the **difference between in-sector shares** of polygon and paired CV loops.
- Central tests the polygon's **in-sector share** for automatic inclusion.

These have different jobs and are not interchangeable. A current test deliberately verifies that a mostly off-map polygon can have shares summing to one without an omitted-sector signal. Central can include that contact from share anyway. [Polygon comparison][polygon], [CV comparison][compare], [explicit denominator test][denominator-test], [central rule][central-rule].

`SectorShare` currently has only `px` and `share` beyond sector identity. Named sectors have no pixel measurements. The named list is a union across runs, so central's OR rule admits a sector named by one run even if geometry disagrees. `mark.redcap` is also unsuitable as a filtered final sector list: code takes all polygon contacts when any exist, otherwise the named list. [Output models][models], [REDCap aggregation][sides].

## What coverage buys

Illustrative arithmetic, not a measured case: a broad mark has 20,000 in-sector pixels. It covers 1,200 pixels of a 2,000-pixel sector. Share is 6%, so the 15% rule misses it. Coverage is 60%, so the 50% rule rescues it. This is a legitimate reason to retain both metrics. Neither metric proves the marked region means tumour.

Because the proposed tests are joined with OR, adding coverage can only add sectors. It cannot remove dubious contacts already admitted by share or naming. A tiny mark wholly within one sector still has share 100% even when it covers very little of that sector. [Central OR rule][central-rule], [share calculation][reference].

## Local probe

Read the three existing `Other/output/drawing/*/drawing.json` files locally. Selected group members and standalone marks in Base, Mid and Apex. Computed sector denominators with `count_nonzero(label_image(view) == region_index)` using the inspected drawing code. No source text entered this note.

| Anonymous case prefix | Candidate axial marks | Mark-sector contacts selected by share or naming | Extra contacts from coverage |
| --- | ---: | ---: | ---: |
| `33f35325` | 8 | 12 | 0 |
| `cfc80c0f` | 5 | 8 | 0 |
| `d7783a97` | 6 | 8 | 0 |
| Total | 19 | 28 | 0 |

Including the one urethra candidate produces 20 marks and 29 selected contacts, still zero additions. These are contacts per mark, not unique lesion sectors or accuracy scores.

All saved outputs record extraction Git SHA `630d04169828ce8d8b116b64199384a01e927832`. A read-only Git diff found no changes between that SHA and the inspected PR head in the reference, geometry, polygon-sector, sector-map or crosswalk files used for these calculations. The outputs themselves were not regenerated.

A concrete denominator example is `d7783a97`, `mid.m3`: rasterised mark area 6,643 pixels, in-sector intersection 1,770, sector area 8,705. Its stored share is 100%, whole-mark fraction is 26.64%, and sector coverage is 20.33%. Its named sector already selects it. This demonstrates the denominator distinction, not whether that contact is right. [Local probe input][probe-input].

## Options and tradeoffs

| Approach | Pros | Cons | Assessment |
| --- | --- | --- | --- |
| Current share OR named | Works with current output; central owns selection; no raster dependency. | Small sectors under broad marks can be missed; off-map geometry inflates share; one named run bypasses geometry; CV alone cannot promote a sector. | Best immediate baseline, with visible uncertainty and preserved maybe contacts. |
| Add `sector_px`, central computes coverage | Small producer change; captures sectors that are small relative to a broad mark; central can tune policy without rerunning extraction. | Contract change; depends on exact reference labels; coverage means different things for filled regions and strokes; OR can add false positives. | Sensible optional evidence field. Grade before enabling 50%. |
| Drawing computes richer metrics or sector suggestions | One owner for label maps, masks and their meaning; central consumes numbers; producer can expose full-mark overlap and geometry type. | Exporting only selected/rejected booleans hides evidence and makes drawing thresholds control downstream results. | Prefer metrics plus optional suggestions. Keep final record selection in central. |
| Central recomputes full geometry | Supports independent geometry experiments and future mark redraws. | Needs reference maps, raster rules, clipping, stroke thickness and versions; duplicates producer logic; does not create independent evidence. | Unnecessary for the hackathon. Ask drawing to recompute after geometry edits. |

## Concrete contract changes worth considering

1. If adding coverage, let drawing provide either `sector_px` or a documented `sector_coverage`. Keep the existing raw intersection and share. Declare the coordinate frame and reference-map/raster version or hash. Validate a positive denominator and `0 <= px <= sector_px`.
2. Also expose full rasterised mark area, for example `raster_area_px`, and its fraction inside all sectors, for example `in_map_fraction`. That addresses the denominator ambiguity coverage alone cannot fix. Declare a measurement kind that distinguishes filled regions, open strokes and ink-only pixels.
3. Keep drawing disagreement thresholds separate from central's versioned selection policy. Record each selected sector's reason, such as named, share or coverage. Retain failed contacts as alternatives. Automatic inclusion in a draft does not mean doctor acceptance for export.
4. Compare baseline and coverage proposals on 5 to 8 grading sheets, as the drawing worktree requires. Include broad marks over small sectors, outside-gland outlines, open arcs, and disagreement between naming, polygon and CV. Count corrected and extra sectors per rule before choosing a threshold. [Required grading format][grading].

Only this research note was added. No implementation, spec or existing output was changed, and no Git write operation ran. No scan or extracted text was sent externally.

[drawing-goals]: /home/jindris/Projects/Rakathon26-drawing/Other/IMAGE-PIPELINE-SPEC.md:7
[schema]: /home/jindris/Projects/Rakathon26/data_schema/STRUCTURE.md:200
[reference]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/reference.py:133
[geometry]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/geometry.py:10
[cv]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/cv_regions.py:29
[polygon]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/polygon_sectors.py:14
[compare]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/compare.py:65
[denominator-test]: /home/jindris/Projects/Rakathon26-drawing/tests/test_drawing_polygon_sectors.py:70
[central-rule]: /home/jindris/Projects/Rakathon26/Other/CENTRAL-SPEC.md:191
[models]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/models.py:68
[sides]: /home/jindris/Projects/Rakathon26-drawing/drawing_pipeline/orientation.py:166
[probe-input]: /home/jindris/Projects/Rakathon26-drawing/Other/output/drawing/d7783a97-acfd-4fdc-b7f6-3b9a209c83f9/drawing.json
[grading]: /home/jindris/Projects/Rakathon26-drawing/Other/IMAGE-PIPELINE-SPEC.md:274
