# Raw scan to PI-RADS reference alignment

## Recommendation

Use one whole-page projective homography from the scan to the ctsit 513 × 631 reference. Estimate it with ORB matches and RANSAC, then refine with ECC only after the homography gives a close start. Try SIFT if ORB matches are sparse. Keep the original scan and transform matrix. Use the warped image as an overlay, not as the only evidence copy.

Check match count, RANSAC inlier ratio, inlier spread over the page, reprojection error, and doubled printed lines in the overlay. Check residuals in each axial view. Reject a page if the inliers cluster in one diagram or a view remains visibly off. Offer a manual fallback that records four widely spaced, non-collinear printed landmarks on the scan and reference. Keep an extra landmark for validation when possible. Do not let separate per-view transforms silently change the page frame.

Estimate, not measured: 3 to 4 hours for the reference transform, quality gates, and four-landmark fallback, then 1 hour to inspect overlays on five sheets. The actual COMPARE choice codes still need a private data dictionary check.

## Map and crosswalk

The ctsit map contains 41 `<area>` polygons. Its `coords` are ordered x,y pairs. The HTML standard defines these as CSS-pixel distances from the image's left and top, so the origin is upper-left, x increases right, and y increases down. The PNG is 513 × 631 pixels. The largest map coordinates are x=505 and y=602. Sources: [ctsit map HTML](https://github.com/ctsit/imagemap/blob/master/maps/pirads_v2.1.html), [ctsit PNG](https://raw.githubusercontent.com/ctsit/imagemap/master/img/pirads_v2.1.png), [HTML image-map coordinate definition](https://html.spec.whatwg.org/multipage/image-maps.html).

I visually compared the ctsit figure with `Other/data/schema/Schema_0001.jpg`. The layouts match: coronal and sagittal views at left, seminal vesicles at upper right, Base, Mid, and Apex axial views down the right, and urethra below. The ctsit art is colorized. This confirms the arrangement, not pixel-identical printing or sector-boundary accuracy. The ctsit PNG carries an ACR 2019 attribution. The module's software license does not by itself establish rights to the image artwork. See the [ctsit README](https://github.com/ctsit/imagemap) and [module license](https://github.com/ctsit/imagemap/blob/master/LICENSE).

Codes below apply the requested tokens: `afs` for anterior fibromuscular stroma, `sv` for seminal vesicles, `pza` for anterior peripheral zone, `pzpl` for posterolateral peripheral zone, `pzpm` for posteromedial peripheral zone, `tza` for anterior transition zone, `tzp` for posterior transition zone, and `cz` for central zone. `rs` and `ls` follow the ctsit Right and Left titles, not screen position. `†` means the code is derived from the requested pattern but could not be checked against the private COMPARE choice list. `‡` means ctsit does not state a seminal-vesicle level; `base` is an inference that needs confirmation. The title column preserves ctsit's spelling, including typos.

| ctsit key | ctsit title | proposed COMPARE code | status |
|---:|---|---|---|
| 1 | Right seminal vesicles | `sv_base_rs` | †‡ |
| 2 | Left seminal vesicles | `sv_base_ls` | †‡ |
| 3 | Right anterior fibromuscular stroma base | `afs_base_rs` | † |
| 4 | Left anterior fibromuscular stroma base | `afs_base_ls` | † |
| 5 | Right anterior peripheral zone base | `pza_base_rs` | † |
| 6 | Left anterior peripheral zone base | `pza_base_ls` | † |
| 7 | Right anterior transition zone base | `tza_base_rs` | † |
| 8 | Left anterior transition zone base | `tza_base_ls` | † |
| 9 | Right lateral posterior peripheral zone base | `pzpl_base_rs` | † |
| 10 | Left lateral posterior peripheral zone base | `pzpl_base_ls` | † |
| 11 | Right posterior reansition zone base | `tzp_base_rs` | † |
| 12 | Left posterior transition zone base | `tzp_base_ls` | † |
| 13 | Right centeral zone base | `cz_base_rs` | † |
| 14 | Left central zone base | `cz_base_ls` | † |
| 15 | Right medial posterior peripheral zone base | `pzpm_base_rs` | † |
| 16 | Left medial posterior peripheral zone base | `pzpm_base_ls` | † |
| 17 | Right anterior fibromuscular stroma mid | `afs_mid_rs` | † |
| 18 | Left anterior fibromuscular stroma mid | `afs_mid_ls` | † |
| 19 | Right anterior peripheral zone mid | `pza_mid_rs` | † |
| 20 | Left anterior peripheral zone mid | `pza_mid_ls` | † |
| 21 | Right anterior transition zone mid | `tza_mid_rs` | † |
| 22 | Left anterior transition zone mid | `tza_mid_ls` | † |
| 23 | Right lateral posterior peripheral zone mid | `pzpl_mid_rs` | † |
| 24 | Left lateral posterior peripheral zone mid | `pzpl_mid_ls` | † |
| 25 | Right posterior transition zone mid | `tzp_mid_rs` | † |
| 26 | Left posterior transition zone mid | `tzp_mid_ls` | † |
| 27 | Right medial posterior peripheral zone mid | `pzpm_mid_rs` | † |
| 28 | Left medial posterior peripheral zone mid | `pzpm_mid_ls` | † |
| 29 | Right anterior fibromuscular stroma apex | `afs_apex_rs` | † |
| 30 | Left anterior fibromuscular stroma apex | `afs_apex_ls` | † |
| 31 | Right anterior peripheral zone apex | `pza_apex_rs` | † |
| 32 | Left anterior peripheral zone apex | `pza_apex_ls` | † |
| 33 | Right anterior transition zone apex | `tza_apex_rs` | † |
| 34 | Left anterior transition zone apex | `tza_apex_ls` | † |
| 35 | Right lateral posterior peripheral zone apex | `pzpl_apex_rs` | † |
| 36 | Left lateral posterior peripheral zone apex | `pzpl_apex_ls` | † |
| 37 | Right medial posterior peripheral zone apex | `pzpm_apex_rs` | † |
| 38 | Left medial posterior peripheral zone apex | `pzpm_apex_ls` | † |
| 39 | Right posterior transtion zone apex | `tzp_apex_rs` | † |
| 40 | Left posterior transtion zone apex | `tzp_apex_ls` | † |
| 41 | External urethral sphincter | `urethra` | † |

Keys 11, 13, 39, and 40 contain apparent spelling errors in the source titles. Their proposed zones follow the corresponding left/right and level entries. Key 41's proposed field label follows the project description, but the exact REDCap choice value was not available here. The ctsit source verifies all keys and titles. It does not verify these COMPARE codes.

## Alignment methods

| Method | Use here | Main limit |
|---|---|---|
| ORB + descriptor matching + RANSAC homography | First choice. Fast CPU baseline. RANSAC rejects inconsistent point matches and returns an inlier mask. | Similar repeated diagrams can produce plausible wrong matches. Ink and reverse-side show-through add features absent from the clean reference. RANSAC can accept a wrong but geometrically consistent cluster. Require inliers spread across the sheet. |
| SIFT + RANSAC homography | Fallback if ORB gives too few or clustered matches. The OpenCV example uses SIFT, a ratio test, RANSAC, and exposes the inlier mask. | More computation than ORB. It still cannot resolve repeated panels from geometry alone. |
| AKAZE + RANSAC homography | Another CPU feature-detector option to compare if ORB and SIFT are weak. | No evidence found that it helps on this form. It shares the same repeated-layout ambiguity. |
| ECC refinement | Refine a good initial transform by maximizing image-intensity correlation. OpenCV supports translation, Euclidean, affine, and homography models. | It is local optimization. Large displacement needs a close initial transform. It can fail to converge, and hand marks or show-through can pull the score. Mask unstable regions and inspect the warped overlay. |
| One whole-page transform | Preferred for a flat scan. A single homography keeps the left views, axial views, and all sectors in one coordinate frame. | It cannot correct page curl or local print distortion. |
| Independent per-view transforms | Use only as a diagnosed local correction when one panel has residual error after page alignment. | Base, Mid, and Apex look alike. Independent fits can swap correspondence or create inconsistent page coordinates. |

OpenCV's feature-matching tutorial covers ORB/Hamming and SIFT/ratio matching. Its homography tutorial states that four correct point pairs are the minimum, uses RANSAC, and returns the inlier mask. Its ECC documentation requires a rough initialization for strong displacement and says non-convergence raises an exception: [feature matching](https://docs.opencv.org/4.x/dc/dc3/tutorial_py_matcher.html), [homography](https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html), [ECC](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html).

The failure risks in the table are inferred from how the methods work, not observed on our scans. OpenCV documents AKAZE as an alternative keypoint detector and descriptor: [AKAZE reference](https://docs.opencv.org/3.0-alpha/modules/features2d/doc/feature_detection_and_description.html).

Learned matchers are optional fallbacks, not the first path. The authors' CPU results on a separate 1,200-pixel image-matching benchmark were 1.33 pairs/s for XFeat, 0.31 for LightGlue, and 0.06 for LoFTR on an i7-6700K. These are not measurements on our scans. XFeat's authors also report real-time CPU inference on VGA images. LightGlue's repository reports CPU inference and has code paths for CPU, though the common example uses CUDA. LoFTR's supplied demo uses CUDA. RoMa estimates dense correspondences and certainties, but its repository gives no CPU timing. Use learned matching only if classical matches fail, resize first, and measure on our pages before choosing it. Sources: [XFeat](https://github.com/verlab/accelerated_features), [LightGlue](https://github.com/cvg/LightGlue), [LoFTR](https://github.com/zju3dv/LoFTR), [RoMa](https://github.com/Parskatt/RoMa), [XFeat CVPR supplement benchmark](https://openaccess.thecvf.com/content/CVPR2024/supplemental/Potje_XFeat_Accelerated_Features_CVPR_2024_supplemental.pdf).

## Reusable code and failure handling

- [Bishara et al. body-map code](https://github.com/ambishara/body_maps_ijerph/blob/main/digitize_body_maps.py) resizes and crops scans, matches ORB descriptors, estimates a RANSAC homography, warps each body-map crop, then removes printed template lines. Reuse the matching, homography, crop, and warp pattern. Do not reuse its line-whitening step without redesign: it can erase hand marks where they cross printed lines. The repository is MIT licensed: [license](https://github.com/ambishara/body_maps_ijerph/blob/main/LICENSE). The inspected code does not use the RANSAC inlier mask for acceptance and has no manual registration fallback.
- [SDAPS recognition code](https://github.com/sdaps/sdaps/blob/master/sdaps/recognize/buddies.py) registers questionnaires from configured page marks and computes a pixel-to-page matrix. Its [GUI code](https://github.com/sdaps/sdaps/blob/master/sdaps/gui/buddies.py) supports dragging page corners and recomputing the matrix. Reuse the separation between registration failure and operator correction. SDAPS expects page marks, which these scans do not have.
- [OMRChecker](https://github.com/Udayraj123/OMRChecker/blob/master/src/processors/CropOnMarkers.py) has marker-based four-point perspective rectification and a page-boundary cropper. These are useful only if matching markers or a clear page boundary exist. Its README says generic `--autoAlign` is deprecated. Its error path records preprocessing failure and skips recognition. Reuse the explicit failure record, not its marker assumptions.
- [queXF registration source](https://github.com/ACSPRI/queXF/blob/master/functions/functions.image.php) estimates rotation, x/y scale, and offsets against a blank form scanned the same way. Its manual calls for corner alignment lines on custom forms. This is a useful model for template-coordinate transforms, but it is not a perspective homography and cannot add marks to our fixed form.

For this sheet, fail alignment when matches cluster in one repeated view, the homography flips or implausibly stretches the page, reprojection residuals are high, ECC fails, or printed lines do not overlay. Save the failure reason and keep the page out of automatic sector export. In manual mode, ask for four corresponding printed landmarks spread across the full page. Four points define the homography; a separate fifth landmark can expose a bad click or wrong correspondence. SDAPS provides a precedent for draggable-corner correction. The thresholds still need review against our scans.

## Sources checked 2026-10-16

All web claims above were checked against upstream project code, official documentation, or the cited paper supplement on this date. The local comparison used only `Schema_0001.jpg`. No scan was uploaded. No probe, script, model download, install, or test was run. The repository search did not find a REDCap data dictionary.
