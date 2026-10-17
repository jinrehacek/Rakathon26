# Handwriting isolation probe

Local OpenCV implementation: `scripts/extract_handwriting.py`. It aligns a colour copy, estimates the printed grey background from reference shades, combines neutral darkness and Lab colour residuals, and saves a candidate mask. The black display layer uses exactly that mask. It does not widen strokes, join gaps, fill outlines or read words.

Eight sheets were run: 1, 3, 7, 13, 14, 17, 27 and 33. These include pink, yellow, green, red, dark blue, pencil notes and broad pencil shading. All eight passed the script's registration checks. Processing took about 3 to 4 seconds per sheet on this host. This is a probe, not a measured extraction-accuracy benchmark.

Visual inspection covered Base, Mid, Apex, coronal and sagittal views on all eight sheets. Coloured outlines, small circles, arrows and many notes are recovered. Scan 13 exposes incomplete broad pencil shading, particularly at printed text and boundaries. Some faint stroke segments are missing; colour fringes, specks and printed-background remnants can survive. These masks require review before later interpretation.

The script saves full-page aligned colour evidence, neutral difference and colour-residual images, estimated background, candidate and uncertainty masks, original-colour ink, an opaque black ink layer, and black handwriting over the colour reference. Seven view crops retain page bounds, transforms back to the source and a crop-edge coverage flag. Outputs are under the git-ignored `Other/output/handwriting/`.

Near printed boundaries the neutral detector is conservative. Colour remains eligible there. Neutral handwriting coincident with printed black pixels can be inseparable. Suppressed residuals remain in the uncertainty image. Thin peripheral scanner-border components and the known printed Rakathon footer are excluded from the displayed handwriting. No anatomical side or lesion identity is assigned.

Five automated tests cover an unmarked template, faint yellow, coloured strokes crossing print, broad neutral shading, an open arc, exact mask-to-display geometry and rejection of a blank page. Original scan hashes are checked during processing. Full-resolution processing outputs are PNG; the compact viewer uses compressed colour previews.

Run from the repository root:

```sh
uv sync
OPENBLAS_CORETYPE=Haswell uv run python scripts/extract_handwriting.py
OPENBLAS_CORETYPE=Haswell uv run pytest -q tests/test_handwriting.py
```

The OpenBLAS setting avoids the illegal-instruction failure observed on this QEMU host. `uv sync` includes the test dependencies. The existing reference assets must be present.
