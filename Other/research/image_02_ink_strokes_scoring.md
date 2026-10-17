# From aligned scan to per-mark sector scores

## Recommendation

Keep the detected ink mask, the grouped mark, the filled-outline candidate, and the sector proposal as separate objects. Subtract the aligned printed template, then threshold residuals in Lab lightness and chroma with local thresholds. Group residual strokes with geometry and page context. Score closed-outline area, raw-stroke contact, and distance to sector boundaries separately. Show a ranked proposal and every sector reached by the uncertainty envelope. Do not turn a score into a clinical yes/no threshold.

The sources back individual image-processing methods. None was tested on drawings like ours, so combining them is our own engineering call. Hours are guesses for one developer starting from aligned scans and the sector map.

## 1. Ink extraction

**Recommendation.** Difference the aligned scan from a clean printed template after local background and exposure normalization. Work in CIE Lab. Combine absolute lightness residual with a/b chroma residual, each scaled to local paper noise, then apply a local adaptive threshold. Lightness retains dark pencil. The a/b channels retain red, pink, and yellow shifts. Do not use a fixed hue or saturation range. HSV hue becomes unstable when saturation is low. Mask known template strokes before grouping so small alignment residuals do not become ink.

Where the paired opposite-side scan exists, align it as a cue for likely show-through and feed that cue into a local color and edge based correction. Do not subtract it blindly because the two sides can warp differently and real writing can overlap. If only one side is available, use a local show-through correction as a secondary estimate. Keep ambiguous pixels for review. Nishida and Suzuki describe local color thresholding and multiscale edge analysis for scanned color documents with show-through. Sauvola and Pietikäinen give a local threshold for degraded document images. The 2025 pain-map pipeline uses an aligned template, adaptive Gaussian thresholding, Canny edges, and dilation to remove printed outlines. Its grayscale mask does not separate mixed ink colors. [Nishida and Suzuki, 2003](https://www.sciencedirect.com/science/article/abs/pii/S0031320303001882), [Sauvola and Pietikäinen, 2000](https://doi.org/10.1016/S0031-3203(99)00055-2), [Bishara et al., 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12469790/).

**Fallback.** Keep the residual as a soft confidence image and show low-contrast candidates in the review overlay. Apply local Sauvola thresholding to the lightness residual. Let a reviewer accept or reject uncertain pixels or components. Lowering one page-wide colour threshold until faint yellow and pencil show up also brings back paper texture and template edges.

**Failure signal.** The mask traces printed borders or dashed sector lines, loses faint marks, or changes substantially under small local-threshold changes. A mark coincident with a printed line is especially uncertain. Route these crops to review.

**Effort.** 1.5 to 2 hours. This estimate assumes an aligned blank template already exists.

**Reusable code.** OpenCV provides Lab/HSV conversion, adaptive thresholding, morphology, and connected components. The Bishara repository is a small reference for template-line removal. Its method is grayscale and needs a separate residual for colored and pencil strokes. [OpenCV color conversion](https://docs.opencv.org/4.x/d8/d01/group__imgproc__color__conversions.html), [OpenCV thresholding](https://docs.opencv.org/4.x/d7/d1b/group__imgproc__misc.html), [body-map code](https://github.com/ambishara/body_maps_ijerph).

## 2. Stroke grouping and outline candidates

**Recommendation.** Preserve the raw ink components. Build a second candidate graph whose nodes are connected components or skeleton paths. Link nearby endpoints when their tangent directions and local stroke widths agree. Use component size, aspect ratio, eccentricity, compactness, closure gap, skeleton branches, color continuity, panel position, and distance to nearby text as features. Peterson et al. classify strokes before grouping them. Bresler et al. use closure, curvature, compactness, and pairwise distances, and keep text-versus-shape decisions revisable. These are useful features, not validated classifiers for this form. [Peterson et al., 2010](https://doi.org/10.1609/aaai.v24i1.7650), [Bresler et al., 2014](https://cmp.felk.cvut.cz/ftp/articles/bresler/Bresler-Phan-Prusa-Nakagawa-Hlavac-ICFHR-2014.pdf).

Treat likely outline, arrow or leader, dimension line, handwriting, P/L letter, non-tumour note such as `zánět`, and unknown as separate candidate labels. An outline tends to close around an organ region. An arrow or size line tends to be elongated and may have a head, ticks, or nearby handwritten dimensions. Text tends to form a local baseline or glyph group. A lone P/L letter near a panel edge is handwriting evidence, not authority for laterality. Keep that decision tied to the report as required by the project schema.

Close only small endpoint gaps relative to the measured stroke width, and preserve the unclosed mask beside the proposed closure. Fill only a closed or explicitly proposed closed contour. For a double-traced loop, compare path overlap, parallel spacing, and endpoint proximity. Keep both traces in the evidence even when they form one candidate group. Large dilation joins arrows, labels, printed borders and outlines into one blob.

**Fallback.** If a candidate overlaps writing, an arrow, or another outline, do not force a class or fill. Keep it as its own diagram-mark subject with its original image region and queue it for doctor review. TuzkaOCR can supply Czech handwriting regions and text as a local cue. Its project code is Apache-2.0, while its model files have a separate CC BY-NC-SA license. OCR output is not a mark classifier. [TuzkaOCR](https://github.com/moravianlibrary/TuzkaOCR).

**Failure signal.** Closing changes component count or filled area sharply, a group crosses a printed sector boundary, or a text/arrow feature is absorbed into the outline. A long open arc or ambiguous double trace should remain unfilled and flagged.

**Effort.** 3 to 4 hours for conservative groups, overlays, and manual correction.

**Reusable code.** OpenCV has `connectedComponentsWithStats`, `findContours`, and morphological closing. scikit-image has skeletonization and per-region features. SciPy has `binary_fill_holes`; its documentation warns that a large structuring element can miss holes separated from the background by thin boundaries. [OpenCV shape analysis](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html), [OpenCV morphology](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html), [scikit-image morphology](https://scikit-image.org/docs/stable/api/skimage.morphology.html), [scikit-image region properties](https://scikit-image.org/docs/stable/api/skimage.measure.html), [SciPy hole filling](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.binary_fill_holes.html).

## 3. Per-sector scores and schema mapping

**Recommendation.** Rasterize the polygons for each axial view from the official 41-sector map in that view's aligned coordinates. Keep three values per mark and sector instead of collapsing them into one score:

- For a closed-outline fill candidate, report `intersection area / mark area` and `intersection area / sector area`. These answer different questions, so show both.
- For an open or uncertain mark, report the fraction of skeleton length inside each sector. Use the original stroke, not an invented interior.
- Report minimum and median distance from the mark stroke or contour to each sector boundary in image pixels. Boundary distance describes proximity. It does not decide sector membership.

The ACR PI-RADS v2.1 map defines 41 regions. The project also references the ctsit REDCap map; verify its key-to-REDCap code table, including key 41, before export. Axial view coordinates map to these polygons. Keep coronal and sagittal mark geometry in their own view coordinates unless a supported transformation maps them to axial sectors. Do not turn schematic pixels or handwritten dimensions into physical scale. [ACR PI-RADS v2.1, 2019](https://cs.acr.org/-/media/ACR/Files/RADS/PI-RADS/PIRADS-V2-1.pdf), [ctsit Image Map](https://github.com/ctsit/imagemap).

Show `proposed` as the top-ranked sector or exact tied sectors for the selected geometry metric. If area and stroke-contact rankings disagree, show both rankings. This is a spatial suggestion, not a chosen registry value. Show `possible` as every sector touched by the raw mark or by the uncertainty envelope made from threshold variants and registration residuals. No clinical cutoff is needed. The rank and the possible set remain visible for the doctor to resolve.

Map the output to `data_schema/STRUCTURE.md`:

- The visible mark and its raw image geometry are a separate diagram-mark subject, with image evidence and a declared page or view coordinate frame.
- The visible stroke geometry is an explicit recorded observation. A computed overlap is a calculated recorded observation supported by that geometry and the sector polygon. A proposed anatomical sector is an inferred recorded observation with `needs review`.
- Keep a proposed fill or auto-closed contour separate from the explicit stroke. Store its supporting geometry and closure reasoning. Do not silently replace the raw outline with it.
- A diagram mark alone does not create a tumour focus. Match it to a reported focus later. Only a doctor-confirmed suggestion can become a reviewed export value.
- Use `unreadable` when relevant pixels exist but cannot be traced reliably. Use `not reported` only when the checked source does not state a property. Use `not assessed` when extraction was not attempted, and `not applicable` with a reason when the property does not apply. An unmarked sector is not an explicit negative.

**Fallback.** If the outline is open or class is unresolved, score stroke contact only and list touched sectors. If sector alignment or orientation is uncertain, show the original crop and all intersected sectors. Let the doctor select the registry value.

**Failure signal.** Area and stroke rankings conflict, most of a mark lies on a sector boundary, or a small geometry change moves its top rank. Display each score and the conflicting candidates. Do not hide disagreement in an aggregate.

**Effort.** 1 to 1.5 hours for the geometric scores and an overlay. Assumes the sector polygons are already importable. The ctsit-to-REDCap key table is a separate 0.75 h step (see [IMAGE_PIPELINE.md](../IMAGE_PIPELINE.md)).

**Reusable code.** OpenCV polygon rasterization and contour operations are enough for sector intersections. scikit-image provides Hausdorff distance for comparing boundaries. [scikit-image Hausdorff distance](https://scikit-image.org/docs/stable/api/skimage.metrics.html), [boundary overlap metrics, 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC5817231/).

## 4. Doctor-facing uncertainty

**Recommendation.** Keep extraction certainty separate from interpretation certainty. Start as `unassessed`; after review, use the schema's qualitative `low`, `medium`, or `high` values and record the reason. These labels are not calibrated probabilities. Show the evidence crop, raw mask, proposed fill, sector overlay, and source mark together.

Compute and show these signals:

- **Alignment:** count spatially distributed template matches and report median and 95th-percentile residual to the aligned template. A local residual near a sector line expands the possible-sector set. Use local residuals because one global score can hide a warped panel.
- **Ink visibility:** record local lightness and chroma contrast against paper noise. Mark pixels close to the adaptive threshold as low extraction certainty.
- **Mask stability:** compare candidate masks from nearby local-threshold settings. Report the changed-pixel fraction and whether the top sector ranking changes. This is sensitivity, not probability.
- **Grouping:** report closure gap in stroke widths, skeleton branch count, candidate-group alternatives, and overlap with OCR regions or known template lines. Keep raw and filled versions when closure is uncertain.
- **Sector ambiguity:** show the number of polygons touched, distance to the nearest boundary in pixels, and score disagreement across area, stroke, and mask variants. A mark on a boundary should produce multiple possible sectors.
- **Cross-source conflict:** retain a flag if report laterality or location conflicts with drawing position or handwriting. Report text controls side; drawing side marks are supporting evidence only.

**Fallback.** If a signal cannot be computed or has not been reviewed, store `unassessed` and a review issue. Do not replace missing evidence with a confidence score.

**Failure signal.** A proposal changes across small threshold changes, has low local contrast, touches multiple sectors, or conflicts with report text. Keep all candidates and block automatic export until a doctor resolves it.

**Effort.** 1.5 to 2 hours for these indicators and review overlays.

## Verified, inferred, and guessed

**Verified.** I read `TASK.md`, `AGENTS.md`, `data_schema/STRUCTURE.md`, and `Other/IMAGE_PIPELINE.md`. I viewed `Schema_0001.jpg`, `Schema_0007.jpg`, and `Schema_0014.jpg`. Those three show pink or red outlines, faint yellow marks, gray handwriting, arrows, and handwritten size notes crossing or sitting beside outlines. This is a visual spot check, not a survey of all scans. The cited sources document the listed methods and library functions. Direct fetches of some publisher pages were blocked, so those claims use the accessible abstract or repository details linked below.

**Inferred.** The proposed Lab residual, conservative grouping rules, per-sector metrics, and uncertainty flags adapt those methods to this drawing set. No source validates their accuracy on these scans.

**Guessed.** Every hour estimate is a planning guess. I did not measure extraction quality, grouping accuracy, sector accuracy, or runtime. I ran no code, probes, tests, scripts, downloads, or installs, and uploaded no scans.

## Dated sources

- Bishara et al. 2025, *A Summary of Pain Locations and Neuropathic Patterns Extracted Automatically from Patient Self-Reported Sensation Drawings*, [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12469790/) and [code](https://github.com/ambishara/body_maps_ijerph). Accessed 2026-10-16.
- Nishida and Suzuki 2003, *Correcting show-through effects on scanned color document images by multiscale analysis*, [paper](https://www.sciencedirect.com/science/article/abs/pii/S0031320303001882). Accessed 2026-10-16.
- Sauvola and Pietikäinen 2000, *Adaptive document image binarization*, [paper](https://doi.org/10.1016/S0031-3203(99)00055-2). Accessed 2026-10-16.
- Peterson et al. 2010, *An Efficient, Classification-Based Approach for Grouping Pen Strokes into Objects*, [paper](https://doi.org/10.1609/aaai.v24i1.7650). Accessed 2026-10-16.
- Bresler et al. 2014, sketch annotation and shape/text separation, [paper PDF](https://cmp.felk.cvut.cz/ftp/articles/bresler/Bresler-Phan-Prusa-Nakagawa-Hlavac-ICFHR-2014.pdf). Accessed 2026-10-16.
- ACR 2019, *PI-RADS v2.1*, [official standard](https://cs.acr.org/-/media/ACR/Files/RADS/PI-RADS/PIRADS-V2-1.pdf). Accessed 2026-10-16.
- ctsit, [REDCap Image Map source](https://github.com/ctsit/imagemap), including its PI-RADS v2.1 map. Accessed 2026-10-16.
- OpenCV 4.x, [color conversions](https://docs.opencv.org/4.x/d8/d01/group__imgproc__color__conversions.html), [thresholding](https://docs.opencv.org/4.x/d7/d1b/group__imgproc__misc.html), [shape analysis](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html), and [morphology](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html). Documentation accessed 2026-10-16.
- scikit-image 0.26, [morphology](https://scikit-image.org/docs/stable/api/skimage.morphology.html), [region measurements](https://scikit-image.org/docs/stable/api/skimage.measure.html), and [Hausdorff distance](https://scikit-image.org/docs/stable/api/skimage.metrics.html). Documentation accessed 2026-10-16.
- SciPy, [`binary_fill_holes`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.binary_fill_holes.html). Documentation accessed 2026-10-16.
- Moravian Library, [TuzkaOCR source and license notes](https://github.com/moravianlibrary/TuzkaOCR). Accessed 2026-10-16.
- Taha and Hanbury 2018, *A Family of Boundary Overlap Metrics for the Evaluation of Medical Image Segmentation*, [paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5817231/). Accessed 2026-10-16.
