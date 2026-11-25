# Step 2 — Seamless multispectral mosaic

See the root `README.md` for the full folder layout and `para.txt` reference.

Quick start: place the color-balanced `.img` scenes, `para.txt`, `NSPO_GRID_vectorization/`
(with `GetBoundaryMask.exe` — requires MATLAB Runtime v9.4 — and `BndPolygonize_v.bat`) and the
`cloud_masks/` cloud-mask folder next to `step2mosaic.py`, then run `run.bat`.

Processing order: the scene whose file name sorts first is the starting scene; the others
follow in order of distance from it (written to `ProcessOrder.txt`).

Note: the cloud-mask folder name is set by the `CLOUD_MASK_FOLDER` constant near the top of `step2mosaic.py`.

Outputs: `mosaic_xs.tif`, `mosaic_cloudmask.tif`, `ProcessOrder.txt`, `transform.npy`, `allWindow.npy`,
`ImgInd.npy`, `Union_gt.npy`, and two rasters per seamline: `*_seamline.img` (the raw
seamline path, for inspection) and `*_seamline_polygon.img` (blend weights used by Step 3).
Several of these are required inputs for Steps 3 and 4.
