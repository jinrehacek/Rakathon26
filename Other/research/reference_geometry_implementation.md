# Reference geometry assets

The generator [prepare_reference_assets.py](../reference/prepare_reference_assets.py) reads the 41 polygons from the upstream [map HTML](https://github.com/ctsit/imagemap/blob/0bf201d6cb95c7eaedb5449b36e4fa1d9cd9907f/maps/pirads_v2.1.html) and matches its 513 × 631 image to the existing 1342 × 1737 reference. It writes [grayscale reference](../reference/pirads_v2.1_grayscale.png), [numbered overlay](../reference/pirads_v2.1_sectors_numbered.png) and [sectors.json](../reference/sectors.json). The original color reference remains unchanged.

The saved mapping uses SIFT matches and a RANSAC homography. This run retained 369 inliers from 427 matches, with a 0.377 px median and 1.127 px 90th-percentile reprojection error. Those errors measure matched image features, not sector boundary precision. The overlay lines up overall; the upstream polygons are coarse, so the feature fit does not establish exact local boundary contacts. The key numbers overlap some printed anatomy labels, but remain readable for inspection.

The map HTML and matching PNG are pinned to upstream revision `0bf201d6cb95c7eaedb5449b36e4fa1d9cd9907f`; their SHA-256 hashes are in `sectors.json`. The upstream [README](https://github.com/ctsit/imagemap/blob/0bf201d6cb95c7eaedb5449b36e4fa1d9cd9907f/README.md) credits Dr. Richard Fan for PI-RADS images and Geoffroey-Allen Franklin for the v2.1 image and mapping. The repository's Apache-2.0 license is copied to [LICENSE.imagemap](../reference/LICENSE.imagemap). That license covers the module code; I found no separate artwork terms, so image redistribution rights remain unverified.

`sectors.json` preserves source keys, names and coordinates alongside transformed coordinates and the homography metadata. REDCap choice codes are explicitly unmapped and unverified.

Run from the repository root with:

```sh
OPENBLAS_CORETYPE=Haswell uv run python Other/reference/prepare_reference_assets.py
```
