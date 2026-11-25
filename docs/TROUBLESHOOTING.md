# Troubleshooting

Known failure modes collected while running the pipeline operationally.

## General

- Step 1 only: ERDAS IMAGINE batch files (`.bcf`, `.bls`) cannot handle spaces, so keep the Step 1 folders and the `SM_BATCH_GMDX_*` paths free of spaces. Steps 2-4 accept paths with spaces.
- When re-running Step 2, delete all previously generated outputs first (`mosaic_xs.tif`, `mosaic_cloudmask.tif`, `*.npy`, `ProcessOrder.txt`, seamline files, `res_union_new.*`), otherwise the run fails. Files inside `NSPO_GRID_vectorization/` can usually stay.
- When re-running Step 3, delete `mosaic_pan.tif` first. Clear `new_pan/` only if the source Pan imagery changed.

## Step 2: intersection goes awry

**Symptom:** intersection points cannot be computed, or are wrong.
**Cause:** pixels that should be `0` (outside the footprint) are not `0` — stray values along the scene border confuse the boundary polygonization.
Step 2 then stops with `SeamlineNotFoundError: Expected 2 seamline endpoints ...`, naming both scenes.
**Fix:** clean the scene borders before mosaicking; verify with the identify tool in QGIS/ArcMap that the area outside the footprint is exactly `0` in all bands.

## Step 2: `No road from target to endnode`

**Symptom:** the seamline search cannot connect the two boundary intersection points.

Case A — the shrunken overlap mask breaks into disconnected pieces (visible as a gap when plotting the mask). Two remedies:

1. Reduce `kernel` in `para.txt`, e.g. `61 → 5`.
2. Enlarge the search tolerance in the code (`pix+30 → pix+500`).

Since the masked-pixel fallback, Step 2 no longer stops here: if neither `kernel` nor `kernel` 11 gives a path, it prints `WARNING: no seamline through valid pixels` and lets the seamline cross masked or no-data pixels at a high cost (`networkx.NetworkXNoPath` used to end the run). Inspect that seamline in its `*_seamline.img`; if it crosses a large masked area, the remedies below still give a better seam.

Case B — the overlap region between the two scenes is extremely thin (a sliver). Such pairs are error-prone and produce a visible dark line at the seam even when they succeed. **Recommendation:** don't mosaic pairs with such minimal overlap; choose scenes with healthier overlap instead.

## Step 3: wrong Pan alignment

The Pan scene extents must match their XS counterparts exactly, or the blend is placed incorrectly. Also remove ERDAS side-car files (`.aux`, `.rrd`, `.rde`) from `raw_pan/` before running.

## Step 4: filled patches look displaced / smeared

**Symptom:** after cloud filling, the filled areas look wrong or shifted.
**Cause:** the color-balance step can slightly crop a scene, so the coordinates looked up during cloud processing no longer match.
**Fix:** before running Step 4, overlay each color-balanced scene on its raw original and confirm the extents match; re-do color balance for cropped scenes.

## Step 4: repeated cloud filling

Running Step 4 again with fresh candidates may or may not improve the result, but it is safe to try: update `cloud_database/`, `raw_pan/`, and the cloud-mask database (used scenes can be removed to save compute time). Only mask value `1` (cloud left unfilled) in `mosaic_cloudmask.tif` is processed. Filled pixels are set to `0`, and `(i + 1) * 10` marks land pixels that the candidate used for filling flags as cloudy in its own cloud mask (`i` is the Step 2 window index). To reprocess an area, set its values back to `1` manually.
