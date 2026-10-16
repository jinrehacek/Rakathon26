# Image implementation plan

> Steps 5 to 7 are revised by [IMAGE-PIPELINE-RECONCILIATION.md](IMAGE-PIPELINE-RECONCILIATION.md): code calculates sectors from the ink mask, Gemini labels marks without polygons or certainty, and calculated sectors are the draft. Follow that file where the two differ.

Agreed direction, 2026-10-16. This file records the implementation decisions from the planning discussion. [IMAGE_PIPELINE.md](IMAGE_PIPELINE.md) contains the earlier research proposal. Extraction and matching must follow [STRUCTURE.md](../data_schema/STRUCTURE.md) and [MATCHING.md](../data_schema/MATCHING.md).

This plan covers drawing processing and per-view extraction. Reference preparation, local alignment, crops and candidate handwriting isolation now have an eight-sheet OpenCV probe. A separate Gemini probe has run two independent readings of eight selected crops with both `gemini-3.5-flash-lite` and `gemini-3.8-flash`, producing 32 validated readings. See [handwriting results](research/handwriting_isolation_probe.md) and [Gemini results](research/gemini_drawing_probe.md) for failures and limits. These probes do not establish extraction accuracy. Report extraction and report-to-lesion matching are another contributor's work.

## Required result

Automatically identify the handwritten additions and the detailed sectors each relevant circle or outline encloses or touches. Retain the panel and sector location, such as TZa at Base, TZp at Mid, or PZpl at Apex. Include every involved sector rather than choosing one dominant sector. Record image-side position separately from anatomical side when orientation is unresolved. Hand these observations to the later matching stage, which will associate marks with reported lesions and draft `sur_prostate_regions` for each lesion.

The doctor should confirm the draft and resolve specific choices in a few clicks. The target is less than two minutes per case, not yet measured. There is no separate clinician-labelling phase and no planned fallback that requires the doctor to redraw outlines or enter the sector map manually.

## Image roles

The scans contain a grayscale printed diagram with handwritten additions, usually yellow, pink or red. The extraction target is what the person added. The printed black organ outlines, sector lines and labels are known background and alignment landmarks, not newly detected marks. Some additions are faint, and pencil or black handwriting must remain candidates too. Ink colour does not identify a lesion or establish that a mark depicts tumour.

Use three distinct images:

- **Original colour scan:** retain unchanged as evidence. Aligned copies and original-image VLM crops retain the scan's colour.
- **Grayscale reference:** make a grayscale copy of the clean reference we already have. Align this with the scan and use it to estimate and subtract the printed background.
- **Colour reference:** retain the clean coloured sector map for displaying the recovered handwriting in solid black, together with sector labels, to the VLM and doctor.

Grayscale conversion applies to the clean reference. It must not replace the colour scans with grayscale images. Temporary intensity calculations inside feature matching or subtraction do not change the preserved scan or its colour outputs.

## Reference image and sector geometry

The existing clean reference is [reference/pirads_v2.1_sector_map.png](reference/pirads_v2.1_sector_map.png), extracted from PDF page 38 of the supplied PI-RADS 2019 document at its native 1342 × 1737 resolution. The [resolution search](research/higher_resolution_sector_map.md) found no verified higher-resolution or vector copy of the same map.

Reuse these assets from [ctsit/imagemap](https://github.com/ctsit/imagemap):

- [maps/pirads_v2.1.html](https://github.com/ctsit/imagemap/blob/master/maps/pirads_v2.1.html) defines 41 sector polygons, with numeric keys and anatomical names.
- [img/pirads_v2.1.png](https://github.com/ctsit/imagemap/blob/master/img/pirads_v2.1.png) is the corresponding 513 × 631 reference image.
- The repository's clickable image-map behaviour is a possible starting point for the review screen.

Map the polygon coordinates onto our larger reference and check their boundaries. Their original coordinate frame is the repository's smaller image; simple enlargement does not establish a precise fit. Save the coordinate mapping and inspect small boundary contacts before relying on it.

Build an explicit table from the polygon keys to the actual REDCap choice codes. The repository's numeric keys are not automatically our export values. Check key 41, titled "External urethral sphincter", against the registry's urethra choice. The module code is Apache-2.0; retain source attribution and check artwork terms separately when incorporating the assets.

## Implementation sequence

### 1. Prepare the references

Create a grayscale copy of the existing clean colour reference without changing its dimensions or geometry. Preserve both versions. Set up the 41 polygons in the same reference coordinates.

Keep the reference's printed black outlines, dashed sector lines and labels. This step only converts colour to grayscale; it does not remove the printed lines or extract a line-only image. Any separate printed-line layer used to inspect alignment is diagnostic only.

Grayscale conversion removes colour but does not reproduce the printer and scanner's exact grey values. Treat it as the subtraction reference candidate. Check and, where needed, normalize its brightness and contrast against the printed scan background.

Completion: the colour reference, grayscale reference and sector polygons share a documented coordinate frame, with their boundaries visually checked.

### 2. Pilot alignment only

Start with scans 1, 7, 14, 27 and 33. Use OpenCV on CPU:

The user guarantees that the page is supplied in the correct upright orientation. Registration corrects position, scale, small skew and perspective; it does not need to discover a page rotation or mirror the page. This guarantee does not resolve anatomical P/L interpretation within a drawing.

1. Find printed-template features with ORB and match them between scan and reference.
2. Estimate a whole-page homography with RANSAC, rejecting inconsistent matches.
3. If ORB produces too few or poorly distributed matches, try SIFT.
4. Apply the accepted transformation to a colour copy of the scan. Keep the original unchanged and save the transform and inverse.
5. Overlay reference boundaries and inspect every relevant panel separately, especially near handwritten outlines.

Check the spread of matching points, local residual error, doubled printed lines and implausible stretching or reflection. Repeated axial panels must not be matched to the wrong level. A good overall page fit does not establish a good fit at every sector boundary.

ECC refinement is optional after a close initial fit. Independent panel corrections are a later option if a specific local error requires them; retain their transforms rather than silently changing coordinates.

Completion: inspect alignment around marks in each panel and record failures. This pilot establishes registration feasibility, not extraction accuracy. No subtraction or VLM is needed for this first pilot.

### 3. Crop each view with context

After alignment, define separate crops for Base, Mid, Apex, the coronal view and the sagittal view. Include seminal-vesicle and urethral regions where needed for the full 41-choice map. Process each view in its own request, rather than asking a model to interpret the whole sheet at once.

Give each crop a configurable margin around the view. Preserve the whole organ outline, panel label, nearby P/L annotations and relevant notes or arrows. If a mark or note reaches a crop edge, expand the crop or flag incomplete coverage. Do not crop tightly to a detected circle and hide the sector context.

Use corresponding crop bounds for the original colour image, grayscale reference, colour reference and sector geometry. Save each crop's page offset, dimensions and transforms so its evidence can be traced back to the original scan.

Preserve handwritten P/L annotations in the crop and record their visible location. Anatomical-side interpretation is deferred to a later stage. Image-left and image-right remain pixel positions; the correct upright page orientation does not establish patient side. Coronal drawings can use a mirrored convention. Do not silently mirror pixels or infer anatomical side just to make a mark fit a sector name. Retain page-side location and any unresolved mapping for the later orientation and report-matching work under the project rules.

The coronal and sagittal views do not display the same detailed sector grid as the axial views. Extract the marks, level or extent and other visible location information they actually support. Do not invent detailed sector assignments that the crop does not establish.

Completion: each crop contains its full view and relevant context, has a documented coordinate frame and retains any unresolved orientation or coverage issue.

### 4. Subtract the printed background and enhance the handwriting

For each crop, compare the colour scan with the grayscale reference in the same aligned coordinate frame. Subtract or suppress the known printed background to estimate the handwritten additions, using the background difference together with colour information from the scan. Preserve the source colour scan and extraction mask for inspection. Render the recovered handwriting as opaque black over the clean coloured reference so faint, translucent strokes are easy to see. The extracted layer should contain handwriting, not the printed black sector lines; those known boundaries remain available in the reference map.

Increase the detected strokes' opacity and contrast without increasing their width or changing their position. "More visible" means solid black, not thicker. Do not dilate, expand, reconnect or redraw the strokes for display. Preserve the recovered stroke geometry and extraction uncertainty separately from the black display layer.

Use colour as a detection aid, not as the only filter. Faint yellow, pencil, black ink and strokes crossing printed lines must remain possible marks. A fixed global saturation threshold is insufficient as the sole detector. Avoid indiscriminately deleting every template-line pixel, which can also delete a crossing outline.

Save an inspectable background-difference image, candidate-ink mask and solid-black handwriting layer. Overlay the black layer on the clean coloured reference. Keep the original colour crop separately for the original-image pass and doctor review. Processing must not invent a connecting stroke or turn an uncertain open arc into an unquestioned closed circle.

Completion: compare processed and original crops on the pilot scans. Record missing strokes, background remnants and processing artefacts. Background removal is not accepted merely because the composite looks cleaner.

### 5. Read each crop in two separate Gemini passes

Use Gemini for the first probe, with the same selected model in both passes. Keep the exact model ID, provider route and image-resolution settings configurable. The specific model and production provider remain open; current candidates and retention conditions are in [vlm_stage_options.md](research/vlm_stage_options.md). Gemini is an agreed probe choice, not a selected production ZDR route.

Send one view per request, with the margins and orientation context defined above. Keep Base, Mid, Apex, coronal and sagittal requests separate. Separate requests may run concurrently, but their results must retain their own panel identity.

- **Pass A:** read the original colour crop without ink enhancement or CV candidate suggestions.
- **Pass B:** read only the modified crop: solid-black recovered handwriting on the coloured reference with sector labels or numbered overlays. Do not include the original crop in this request.

Neither pass sees the other pass's answers. Drawing extraction does not receive the report; report matching happens later. The original-image pass must inspect the full panel, not just CV-detected candidates, so it can find marks that subtraction missed.

For each visible handwritten mark, return its panel, approximate location, proposed kind, supported detailed sector set, uncertain sector candidates and supporting image region. Keep visible sector labels and page-side location separate from any uncertain patient-side mapping. Distinguish circles or outlines from arrows, measurements, handwriting and non-tumour annotations. Printed template lines are background, not mark candidates. Include a reason for uncertainty. Allow "mark present, sector contact unclear" rather than forcing a definite answer.

Keep both passes as separate extraction attempts, with their inputs, processing versions, model versions and evidence references. Use the schema's observation statuses, bases and qualitative certainty terms. Preserve each attempt's observations when comparing the results.

Completion: both passes produce inspectable mark-level proposals, including uncertain and unmatched candidates. Exact VLM polygons are optional; the required output is the detailed sector set for each mark.

### 6. Compare marks and sectors

Match corresponding marks within each panel using their locations and evidence, not arbitrary numbering. Compare mark counts and sector sets per mark. Equal combined sector lists for a whole panel do not establish agreement if the passes identified different marks.

Where CV can recover a defensible closed outline, compare its filled interior plus boundary stroke with all sector polygons. A sector entirely inside a circle counts even if the circle's stroke never crosses it. A genuine boundary touch also counts. Do not discard a real contact solely because its area is small. Uncertain contacts become specific review choices.

Only relevant outline geometry contributes to this overlap check. An arrow or handwritten word crossing a sector does not establish lesion involvement. Do not force-fill an open arc whose interior is unclear.

Use Pass B, the modified-image result, as the preselected draft. Preserve both passes' observations. Every detected disagreement becomes a specific doctor question with both crops available, rather than silently accepting the preselection. Retain original-only marks as unresolved candidates too. A preselected result is not reviewer acceptance, and unresolved issues still block final export. Two passes agreeing is a consistency check, not proof of correctness; both can share an alignment error. Alignment checks remain a separate prerequisite.

Completion: each disagreement identifies the mark and sector involved and supplies the original and processed evidence for a short confirmation choice.

### 7. Hand off drawing observations and review questions

Return per-view marks, sector proposals, orientation observations, uncertainty and evidence references to the contributor handling report extraction and cross-document matching. This image stage does not implement report extraction or introduce a separate report-to-lesion model call. Several marks across panels may depict one focus; mark count is not lesion count. An unmatched drawing mark never creates a lesion by itself.

Use the report to decide patient side under the project rules. Keep drawing position and handwritten P/L as supporting evidence, preserving disagreements. If the report supplied a side assignment, do not count that assignment as independent drawing confirmation of the report. Coronal orientation may differ from axial orientation.

Provide the original and processed crops, sector overlays and a queue of specific image questions. Examples include confirming an extra circle, including a marginal sector, excluding an arrow or resolving a view's mirrored orientation. The downstream review screen combines these with the report and draft lesion records. Agreement can prefill a draft; a doctor still confirms the record before export.

Use a bounded automatic retry with another crop or processing variant when results are unusable. If the case remains unresolved, retain the issue and block its final export. The retry limit is still an implementation choice. There is no requirement to force an answer for every scan.

Completion: drawing observations and review choices are traceable to their original crops and scans. Preserve rejected alternatives and source conflicts. The later matching, review and REDCap export stages use this handoff under TASK.md and the schemas.

## Execution boundaries and remaining checks

Explain each processing stage to the user before running it. This update records planning decisions and does not run image processing or a model call. The user has agreed to Gemini as the first probe and explicitly permits using these public, anonymised hackathon scans without ZDR. Retention is not a blocker for this sample probe. Production data and protected future benchmark material remain subject to TASK.md's separate requirements; the sample permission does not authorize other services or identifiable production records. Select the concrete model and API route when preparing the probe.

Keep patient-linked inputs and outputs in an ignored local directory before their first write. The public reference images and this plan contain no patient records.

Still to establish through the pilots: reference shading compatibility, local alignment precision, ink preservation, VLM model and prompts, latency, retry limits and doctor correction time. There is no clinician-labelled benchmark in this plan, so report pilot observations without claiming measured extraction accuracy.
