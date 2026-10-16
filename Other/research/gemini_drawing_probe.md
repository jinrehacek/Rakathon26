# Gemini drawing probe

Run on 2026-10-16 through the Gemini Developer API using the session-authorized anonymised hackathon crops. The separate runner is `scripts/probe_gemini.py`; its prompt is `prompts/gemini_drawing.md`. The environment is managed by `uv sync` and `uv run`, with dependencies in `pyproject.toml` and `uv.lock`.

## What ran

Both `gemini-3.5-flash-lite` and `gemini-3.8-flash` read the same eight crop pairs: 1 Mid, 3 coronal, 7 Base, 13 Apex, 14 Mid, 17 Mid, 27 sagittal and 33 Apex. The response model-version strings matched the requested model IDs. Each model received one original-colour request and one modified-image request per crop. Every request contained one image and a fresh contents message. Neither pass received the other answer, CV candidate geometry or the pathology report.

Inputs were full-resolution PNG crops, with high media resolution, low thinking and temperature 1.0. Responses were schema-constrained JSON, validated locally for field types, coordinates, unavailable values and open geometry. The runner allows one retry for transient transport errors, truncated output or invalid JSON. Permanent API errors do not retry.

The successful comparison contains 32 readings, all valid on the first attempt. Earlier, four image requests were rejected with HTTP 400 while checking the API contract. Small text-only requests isolated nested array bounds as the rejected schema feature. Removing those bounds from the API schema worked; local validation still enforces them. Those rejected requests are preserved separately and excluded from the model comparison.

## Observed results

Gemini 3.8 Flash is the better candidate for the next probe. Lite can identify some simple marks, but it missed obvious additions in scan 7 Base: one mark per pass, compared with nine and eight from 3.8. Visual inspection of that crop supports several outlines, margin letters, an arrow and a note. More reported marks does not by itself mean more correct marks.

Across the eight crops, Lite proposed 49 marks and 3.8 proposed 65, counting both passes separately. These are proposal counts, not lesion counts or recall measurements. Median request time was 4.02 seconds for Lite and 9.81 seconds for 3.8. Total prompt/output tokens were 40,154/19,295 for Lite and 40,154/17,194 for 3.8. These figures exclude the initial API-contract checks and do not establish a billed case price.

Both models returned approximate polygons or polylines. Visual inspection covered all eight crop pairs for both models. Many 3.8 contours on modified axial views followed the recovered outlines closely, especially scan 14 Mid and scan 33 Apex. Lite contours were frequently displaced, oversized or unrelated to the described mark. Both models failed on some longitudinal and faint-original contours. In scan 17 Mid, 3.8's modified-image outline included crossing segments. Polygon output is useful as an inspectable proposal; it is unsuitable as automatic sector-contact truth.

A diagnostic compared each predicted contour with the existing CV ink mask. The median of per-contour median distances was 13.37 px for Lite and 0.95 px for 3.8, measured in the prepared crop frame. This compares different proposal sets against an incomplete CV mask. It is not geometric accuracy, segmentation IoU or a clinician-labelled benchmark. Broad pencil shading in scan 13 is already incomplete in the modified input.

An additional geometry review flagged 13 of Lite's 37 traces and 15 of 3.8's 43 traces for disagreement with their own bounding box, a crossing contour or zero area. One 3.8 contour had crossing segments. Raw model output remains unchanged. The runner suppresses filled-area overlap for flagged geometry, preserves open polylines and retains every nonzero overlap when a contour is eligible. Reference polygon contacts remain calculated suggestions with unconfirmed patient side and no verified REDCap choice-code mapping.

The two readings also expose different errors. Scan 1's modified-image pass merged pink/yellow marks that the original-image pass distinguished. On scan 7, the original image retained a faint pencil outline that preprocessing missed. Agreement, equal mark counts or equal panel-level sector lists do not establish per-mark correctness. Automatic correspondence and reconciliation remain later work.

## Files and checks

The first successful crop is under `Other/output/gemini-probe/live-contract-2/`; the other seven are under `Other/output/gemini-probe/eight-crop-comparison/`. `combined_summary.json` links the 32 original results. `polygon_review.json` adds the later geometry diagnostics while preserving all model observations. Each reading keeps its input, prompt/configuration, hashes, raw API response, usage and validated result. All case-linked outputs are git-ignored.

Fourteen local tests passed, covering image-request isolation, schema and semantic validation, missing values, bounded retries, open arcs, coordinate conversion, retained small contacts, crossing contours and the existing OpenCV tests. All 32 readings were revalidated against their saved raw responses and their input/source hashes were checked. The uv lockfile check passed. The retry path was tested with mocked responses; no live comparison reading needed it.

For this probe, keep 3.8 Flash as the primary reader and retain both image passes. Keep model contours optional and visible for review. Lite and polygon-driven sector assignment need stronger evidence before being used to prefill an accepted result. No report matching, production service or export was implemented.

## API references checked

Google documents the selected [3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) and [3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) image inputs. The [image guide](https://ai.google.dev/gemini-api/docs/image-understanding) describes normalized boxes and polygon proposals. The [structured-output guide](https://ai.google.dev/gemini-api/docs/structured-output), [GenerateContent reference](https://ai.google.dev/api/generate-content) and [media-resolution guide](https://ai.google.dev/gemini-api/docs/media-resolution) informed the request format. Their documented capabilities do not validate accuracy on these drawings.
