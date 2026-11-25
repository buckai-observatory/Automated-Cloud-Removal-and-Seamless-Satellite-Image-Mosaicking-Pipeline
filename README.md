# Automated Cloud Removal and Seamless Satellite Image Mosaicking Pipeline

[![tests](https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/actions/workflows/tests.yml)
[![Sentinel-2 demo](https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/actions/workflows/demo.yml/badge.svg)](https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/actions/workflows/demo.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-BA0C2F.svg?style=flat-square)](LICENSE)
[![Paper](https://img.shields.io/badge/Paper-10.1016%2Fj.acags.2026.100387-0A7BBB.svg?style=flat-square)](https://doi.org/10.1016/j.acags.2026.100387)
[![Software DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23404699.svg)](https://doi.org/10.5281/zenodo.23404699)
[![Documentation website](https://img.shields.io/badge/documentation-website-0A7BBB.svg?style=flat-square)](https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/blob/main/notebooks/sentinel2_walkthrough.ipynb)
[![Try it: CloudPeel](https://img.shields.io/badge/try%20it-CloudPeel-2E8B57.svg?style=flat-square)](https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/cloudpeel/)

An end-to-end, largely automated pipeline that turns individual orthorectified satellite scenes into a single color-balanced, seamless, cloud-filled mosaic — for both the multispectral (XS) and panchromatic (Pan) products, together with a mosaic-wide cloud mask.

Documentation website, with every step's README and an API reference generated from the docstrings: <https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/>

**Try it**

- **In your browser, nothing to install:** [CloudPeel](https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/cloudpeel/) shows mosaics made with this pipeline before and after cloud filling; change the cloud tolerance and SSIM threshold and see the result change.
- **In Colab, nothing to install:** the [walkthrough notebook](notebooks/sentinel2_walkthrough.ipynb) runs Steps 2–4 on free Sentinel-2 imagery with figures after each step; [open it in Colab](https://colab.research.google.com/github/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/blob/main/notebooks/sentinel2_walkthrough.ipynb) and choose *Runtime → Run all* (about 5 minutes).
- **On your computer:** after [installation](#installation), `python examples/sentinel2_demo/run_demo.py --workdir demo_output` runs Steps 2–4 on free Sentinel-2 imagery (see [Try it: Sentinel-2 demo](#try-it-sentinel-2-demo)).

If you use this code, please cite the accompanying paper:

> Hsu, H.-J., Tseng, K.-H., Tsai, F., Liu, C.-L., Lo, C.-C., & Moortgat, J. (2026). A novel approach to automated cloud removal and seamless multisensor satellite image mosaicking. *Applied Computing and Geosciences*, 31, 100387. https://doi.org/10.1016/j.acags.2026.100387

The paper is open access: [PDF](docs/paper/Hsu_et_al_2026_Applied_Computing_and_Geosciences.pdf) (© 2026 The Authors; published by Elsevier under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license).

To cite the software itself, use its Zenodo archive: https://doi.org/10.5281/zenodo.23404699 (all versions; each release also has its own DOI).

---

## Pipeline overview

| Step | Folder | What it does | Main tooling |
|------|--------|--------------|--------------|
| 1 | `step1_color_balance/` | Radiometric normalization (color balance) of each raw scene against reference imagery, with dark-area detail preservation | ERDAS IMAGINE 2014 spatial models + `MappingReshapeXS.exe` |
| 2 | `step2_mosaic/` | Automatic seamline detection (sparse-node Dijkstra over image-difference cost) and seamless mosaicking of the color-balanced XS scenes; builds the mosaic-wide cloud mask | Python (`step2mosaic.py`) + `GetBoundaryMask.exe` |
| 3 | `step3_pan_mosaic/` | Mosaics the corresponding Pan scenes reusing the seamlines found in Step 2 | Python (`mosaicPan_block_rs.py`) |
| 4 | `step4_cloud_removal/` | Automatically fills cloud-contaminated areas of the XS and Pan mosaics from a database of candidate scenes, using SSIM-based similarity screening and Poisson blending | Python (`step4cloud_removal.py`) |

Outputs after Step 4:

- `mosaic_xs.tif` — final cloud-filled multispectral mosaic (4 bands)
- `mosaic_pan.tif` — final cloud-filled panchromatic mosaic
- `mosaic_cloudmask.tif` — final mosaic cloud mask: `0` for clear or successfully
  filled pixels, `1` for clouds left unfilled, and `(i + 1) * 10` for land pixels
  flagged by the selected candidate's processed cloud mask. Here `i` is the
  zero-based index of the Step 2 scene window being processed. The value
  identifies that window; it does not identify the candidate scene.
- `*_raw.tif` copies of the pre-Step-4 mosaics for comparison
- `fill_log.csv` — which candidate scene filled each cloud patch (see Step 4)

## Installation

```bash
# Create a conda environment (recommended)
conda create -n mosaic python=3.12
conda activate mosaic

# Install geospatial libraries via conda-forge
conda install -c conda-forge gdal rasterio geopandas shapely

# Install remaining packages
pip install -r requirements.txt
```

On macOS or Linux, a virtual environment with pip is another option (including
Python 3.13). Install GDAL's command-line tools separately, for example
`brew install gdal` on macOS or `sudo apt install gdal-bin` on Debian/Ubuntu,
then run from the repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The pip packages do not install the GDAL commands used by the pipeline.
Make sure `gdalwarp` and `gdal_translate` are available on `PATH`. On Windows,
the conda environment above also provides these tools.

Alternatively, install the pipeline as a package (`pip install .` from a clone; it uses the same `requirements.txt`). This adds one command per step, each taking the prepared working folder (the folder with the step's parameter file) as its argument:

```bash
pip install .
mosaic-step2 path/to/step2_folder   # reads para.txt
mosaic-step3 path/to/step3_folder   # reads para_pan.txt
mosaic-step4 path/to/step4_folder   # reads para_cld.txt
```

The folder must be prepared as for `python step*.py` (Step 2 also needs `NSPO_GRID_vectorization/` there). Running `run.bat` or `python step*.py` inside each folder works as before.

## Requirements

- **Python 3.10+** with the packages in `requirements.txt` (Steps 2–4 run on Windows, macOS and Linux)
- **GDAL command-line tools** on `PATH` (`gdalwarp`, `gdal_translate`; conda-forge's `gdal` package provides them)
- **Windows and ERDAS IMAGINE 2014** for Step 1 only: its workflow also runs Windows `.bat` and `.exe` tools, including `MappingReshapeXS.exe` (later ERDAS versions, e.g. 2018/2020, may produce wrong colors). Without this environment, start at Step 2 with scenes color-balanced by any other tool.
- Optional, Windows only: the original boundary tool in `NSPO_GRID_vectorization/`. Step 2 runs `GetBoundaryMask.exe` through `BndPolygonize_v.bat` only when **MATLAB Runtime R2018a (v9.4)** is installed and the batch file's `bin\` folder of GDAL tools and Python is present (it is not included in this repository). Otherwise, and on macOS and Linux, Step 2 uses an equivalent pure-Python footprint polygonizer.

> **OpenCV version:** Step 4 needs OpenCV < 4.11. From 4.11 on, `cv2.seamlessClone` keeps the destination texture and clouds are not removed. `requirements.txt` pins this, and the test suite checks it.
>
> **8-bit blending:** `cv2.seamlessClone` works on 8-bit images, so Step 4 scales the
> bands to 8 bits for the Poisson blend and back afterwards. Filled pixels are therefore
> quantised to steps of `2**(trueBits - 8)` (16 for 12-bit data). Where the blend
> would go below zero, the pixel is set to one step rather than 0 (no data).

Input data (not included): orthorectified satellite XS scenes (`.raw`/`.img`) with matching Pan scenes and per-scene cloud masks (`.ers` or `.tif`), plus the Step-1 reference images.

> **Configurable canvas extents:** Steps 2 and 3 read `canvas_x_max`, `canvas_y_min` and `canvas_crs` from `para.txt` and `para_pan.txt`. Step 4 reads only `canvas_crs` from `para_cld.txt`; it uses the prepared mosaics and Step 2 window/transform files for its extent. The defaults use Taiwan TWD97 (`EPSG:3826`). For another region, update the bounds in Steps 2 and 3 and use the same CRS throughout all three steps.

> **Land/sea mask:** Step 4 requires a binary land/sea border mask raster (`1` = land, `0` = sea). This file is **not included**. Create or obtain one for your study area and set its path via `seaBorderAddress` in `para_cld.txt`. The mask must use the same CRS and pixel size (`res`) as the XS mosaic, be aligned to the XS pixel grid, and cover the mosaic extent. It does not need the same width, height or origin as the mosaic: Step 4 reads it by window in map coordinates (the Sentinel-2 demo's mask spans the whole area of interest and is larger than its mosaic).

---

## Step 1 — Color balance (ERDAS IMAGINE 2014)

Folder: `step1_color_balance/`

> **Note:** the ERDAS spatial models (`.gmdx`), batch configuration files (`.bcf`), and the compiled boundary-mask tools (`MappingReshapeXS.exe`, `GetBoundaryMask.exe`, `BndPolygonize_v.bat`) were originally developed at the **Center for Space and Remote Sensing Research (CSRSR), National Central University** and the **National Space Organization (NSPO/TASA), Taiwan**. Python source for the table-remapping step is provided in `distrib/runrunrun.py`.

Workflow (drive it with `Auto_2data_test.bat`):

1. **Step1SPOTf** (spatial model `color_balance.gmdx` / snapshot `SM_BATCH_GMDX_012516`): per scene, finds invariant areas against three reference layers and produces a mask, four color lookup tables `col1..4_N.tbl`, and a first balanced image.
2. **`distrib/runrunrun.exe`** (source: `distrib/runrunrun.py`): calls `MappingReshapeXS.exe` on each table group to stretch near-zero DN values so dark areas keep detail → `colX_N.fd.tbl`.
3. **Step2SPOTf** (spatial model `applytable_taibor_noedge.gmdx` / snapshot `SM_BATCH_GMDX_023448`): applies the remapped tables → the final color-balanced scene.

Setup on a new machine:

1. Edit the output folders inside `Step1SPOTf.bcf` / `Step2SPOTf.bcf` and make the `smprocess` line point at the `SM_BATCH_GMDX_*` files (absolute path, no spaces).
2. Build your scene lists from `Step1SPOTf.bls.example` / `Step2SPOTf.bls.example` (tab-separated, one row per scene) and save them as `.bls`.
3. In ERDAS IMAGINE → *Batch*, load the `.bcf`+`.bls` pairs and submit once — this generates `Step1SPOTf.bat` / `Step2SPOTf.bat` for **your** machine (these are machine-specific and intentionally not shipped).
4. From then on, run everything with `Auto_2data_test.bat`.

## Step 2 — Seamless multispectral mosaic

Folder: `step2_mosaic/`. Working-folder layout:

```
step2/
├── run.bat
├── step2mosaic.py
├── para.txt
├── a0000001.img  a0000002.img  ...   # color-balanced scenes from Step 1
├── NSPO_GRID_vectorization/          # GetBoundaryMask.exe + BndPolygonize_v.bat (do not delete)
└── cloud_masks/                      # per-scene cloud masks (.tif preferred over .ers)
```

`para.txt` parameters:

| Key | Meaning |
|-----|---------|
| `path_method` | Seamline cost function: `a6`, `a7`, `a6c`, `a7c`, `a6c_int`, `a7c_int`. Use `a6c_int` for new runs; `a6c`/`a7c` keep historical uint8 arithmetic for reproducibility. |
| `res` | XS resolution (m), e.g. `6` |
| `pan_res` | Pan resolution (m), e.g. `1.5` |
| `resampleTo` | Downsampling factor for seamline detection (recommended `5`) |
| `trueBits` | Actual unsigned DN bit depth, for example `8`, `11`, `12`, `14`, or `16`. Storage uses the smallest fitting unsigned integer container. |
| `imgPath` | Folder containing the input `.img` scenes, absolute or relative to the Step 2 working directory. Outputs and cloud masks still use the working directory. |
| `kernel` | Shrink kernel for seamline detection (odd number, recommended `61`) |
| `canvas_crs` | CRS of the mosaic canvas (e.g. `EPSG:3826`) |
| `canvas_x_max` | Eastern bound of the mosaic canvas (map units) |
| `canvas_y_min` | Southern bound of the mosaic canvas (map units) |
| `startScene` | Optional. Scene to start the mosaic from, e.g. `a0000003` (with or without `.img`). Default: the scene whose name sorts first. |

The supplied `para.txt` and Sentinel-2 demo deliberately use `a6c` to keep the
historical arithmetic used for the paper's method. Set `path_method` to
`a6c_int` explicitly for new runs that should avoid uint8 wraparound; this can
change the selected seamline.

Processing order: Step 2 starts from the scene whose file name sorts first (alphabetically) and adds the others in order of distance from it. Name the scenes so that the one you want to start from, usually a central scene, sorts first, or set `startScene` in `para.txt`. The order is written to `ProcessOrder.txt` and is the same on every operating system.

> **Changed after v1.1.0:** up to v1.1.0, Step 2 started from whichever scene the
> operating system listed first, and Step 4 read its candidates and cloud
> patches in that order too (fixed in #97). Windows lists files by name, so
> results there do not change for typical scene names such as `a0000001.img`.
> On macOS and Linux, Step 2 can now start from a different scene than v1.1.0
> did, which changes the seamlines and the mosaic, and Step 4 can fill some
> pixels differently. To keep a v1.1.0 run's starting scene, set `startScene`
> to the first scene in its `ProcessOrder.txt`.

Outputs: `mosaic_xs.tif` (XS mosaic), `mosaic_cloudmask.tif` (cloud mask mosaic), `ProcessOrder.txt`, `transform.npy`, `allWindow.npy`, `ImgInd.npy`, `Union_gt.npy`, and two rasters per seamline:

- `<scene1><scene2>_seamline.img` for the first pair and `<scene>_seamline.img` for each later scene: the raw seamline path (uint8, `1` on the seamline, `0` elsewhere) on the Step 2 grid. For inspection only; later steps do not read it.
- `<scene1><scene2>_seamline_polygon.img` and `<scene>_seamline_polygon.img`: the feathered blend weights (float32, Pan resolution) that Step 3 reuses.

If no seamline can be found through valid pixels of an overlap (for example when snow, cloud or no-data splits it), Step 2 retries once with `kernel` 11 and then lets the seamline cross masked pixels at a high cost, printing a `WARNING`. Check that seamline in its `*_seamline.img`.

## Step 3 — Panchromatic mosaic

Folder: `step3_pan_mosaic/`.

Copy from Step 2: `transform.npy`, `ImgInd.npy`, `allWindow.npy`, `Union_gt.npy`, `ProcessOrder.txt`, and all `*_seamline_polygon.img` files. Copy `*_seamline_polygon.img.aux.xml` sidecars too if Step 2 wrote any; they are optional and usually absent, so skip them if your shell reports no matches. Step 2 does not require `.ige` files. Add `raw_pan/` and an empty `new_pan/`.

Configure `para_pan.txt` (`res`, `trueBits`, `StartLetter`, `upscale_factor`, `canvas_crs`, `canvas_x_max`, `canvas_y_min`) and run `run.bat`. Output: `mosaic_pan.tif`.

## Step 4 — Automatic cloud filling

Folder: `step4_cloud_removal/`.

```
step4/
├── run.bat
├── step4cloud_removal.py
├── para_cld.txt
├── mosaic_xs.tif  mosaic_cloudmask.tif   # from Step 2
├── mosaic_pan.tif                         # from Step 3
├── allWindow.npy  transform.npy  ProcessOrder.txt   # from Step 2
├── land_sea_mask.img                      # user-provided; see "Land/sea mask" note above
├── cloud_database/                        # candidate XS scenes for filling
├── cloud_masks/                           # cloud-mask database for the candidates
├── raw_pan/                               # candidate Pan scenes
└── cldDatabase/                           # empty working folder
```

Replace the template's `YOUR_PATH` placeholders with your paths. On macOS and
Linux use forward slashes, for example `"CandiImgPath": "/data/cloud_database"`;
forward slashes also work on Windows (`"CandiImgPath": "D:/data/cloud_database"`).
If using Windows backslashes in JSON, escape them as `\\` as the template does.

Two `para_cld.txt` settings control which candidates are used:

| Key | Meaning |
|-----|---------|
| `ssim_threshold` | Minimum SSIM between a candidate and the cloud-free surroundings of a patch (default `0.75`) |
| `cloud_tolerance` | Maximum fraction of a patch that may be cloudy in the candidate itself (default `0.25`) |

SSIM is computed with clouds and sea masked out in both images. A candidate
that covers only part of a patch's window has 0.05 subtracted from its SSIM, so
it needs a raw SSIM of at least `ssim_threshold + 0.05` to be used.

> **Changed after v1.1.0:** up to v1.1.0 the 0.05 penalty was also applied to
> candidates that cover the whole window, and sea was masked out only in the
> candidate (fixed in #72 and #77). With the same settings, Step 4 can therefore
> choose different candidates than v1.1.0, mainly when a candidate's SSIM is just
> above the threshold and in coastal patches, and the `ssim` values in
> `fill_log.csv` are 0.05 higher for candidates that cover the whole window.
> These two fixes do not change which candidates fill the Sentinel-2 demo's
> patches.

Step 4 adds one to the numeric part of the candidate XS scene name to find its
Pan counterpart. For example, `A0000001.img` uses
`raw_pan/A0000002/A0000002_B1.DAT.raw` (SPOT layout) or `raw_pan/A0000002.tif`.

Step 4 also writes `fill_log.csv`, one row per candidate tried for each cloud patch: `window` (index into `allWindow.npy`), `patch` (cloud-patch name, unique within a window), `candidate`, `ssim`, `clear_fraction`, `filled` (`yes`/`no`), `pixels` (patch size), `note` (why a candidate was not used) and `x_min`, `y_min`, `x_max`, `y_max` (the patch window's bounds in the mosaic CRS, so each row can be placed on the map). A patch with no candidate above `ssim_threshold` gets one row with an empty `candidate`. The log does not affect the image outputs.

Run with `run.bat` (or `python step4cloud_removal.py`). See `docs/TROUBLESHOOTING.md` for known failure modes and their fixes.

## Try it: Sentinel-2 demo

The SPOT and Formosat imagery used in the paper cannot be redistributed; to request it, contact the Center for Space and Remote Sensing Research (CSRSR), National Central University, Taiwan. To try the pipeline without it, run Steps 2–4 on free Sentinel-2 imagery:

```bash
python examples/sentinel2_demo/run_demo.py --workdir demo_output
```

See [`examples/sentinel2_demo/README.md`](examples/sentinel2_demo/README.md) for details.

### CloudPeel: explore the results in a browser

CloudPeel is a small website that shows mosaics made with this pipeline before and after cloud filling, for several regions. Visitors can change Step 4's cloud tolerance and SSIM threshold and see the result change, with seamline, cloud-mask and fill-date layers. It is static: Step 4 is run ahead of time for a grid of settings. See [`examples/cloudpeel/README.md`](examples/cloudpeel/README.md) to run it locally or add a region.

Live site: <https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/cloudpeel/>

## Testing

Unit tests for the core seamline, blending and cloud-filling helpers run on any OS (no imagery, ERDAS or Windows tools needed):

```bash
pip install -r requirements-dev.txt
pytest
```

The tests also run in GitHub Actions on Linux and Windows for every push and pull request.

> **Starting without ERDAS IMAGINE:** Step 1 is the only step that needs proprietary software. If you already have radiometrically balanced scenes (from any tool), put them in the Step 2 folder and start there.

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Repository layout

```
step1_color_balance/   ERDAS models, batch configs, table-remapping tool (+ runrunrun.py source)
step2_mosaic/          seamline + XS mosaic script, boundary-mask tools, para.txt template
step3_pan_mosaic/      Pan mosaic script, para_pan.txt template
step4_cloud_removal/   cloud-filling script, para_cld.txt template
docs/                  troubleshooting notes
tests/                 unit tests (pytest)
examples/              Sentinel-2 demo of Steps 2-4; CloudPeel web explorer
notebooks/             walkthrough notebook of Steps 2-4 (runs in Colab)
paper.md               JOSS paper source
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Released under the MIT License (see [`LICENSE`](LICENSE)).
