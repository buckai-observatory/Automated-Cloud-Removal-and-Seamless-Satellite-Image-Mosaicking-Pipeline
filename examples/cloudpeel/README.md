# CloudPeel: cloud-free satellite mosaic explorer

CloudPeel is a small static website for exploring cloud-free satellite mosaics made with the
[Automated Cloud Removal and Seamless Satellite Image Mosaicking Pipeline](https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline).

**Live site:** <https://buckai-observatory.org/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline/cloudpeel/>

Visitors can:
- swipe between the cloudy mosaic (before) and the cloud-filled mosaic (after) on a map;
- change Step 4's **cloud tolerance** and **SSIM threshold** with sliders or
  presets (Cautious / Default / Bold) and watch the result change;
- see how many cloud patches were filled, how much cloudy area is left, and a
  grid comparing every setting;
- turn on a cloud-mask overlay (filled / left unfilled / flagged).

The site has no backend. Step 4 takes only seconds on a region that has already
been through Steps 2-3, so `precompute.py` runs it for every combination of
settings ahead of time (a 5 x 5 grid by default), and the page just switches
between the saved results.

## Get the images

The precomputed images (about 440 MB) are not kept in git, so that cloning the
pipeline stays small. They are attached to the `cloudpeel-data-v1` release of
this repository. Download them into `site/data/` with:

```bash
cd examples/cloudpeel
python fetch_data.py
```

Use `python fetch_data.py --force` to replace an installed image set. The new
archive is fully unpacked in a temporary folder under `site/` before replacing
`site/data/`, so a corrupt archive leaves the installed files intact.

## Demo on any computer

The site is plain files, so any computer with Python 3 can show it; the pipeline
is not needed. Run `python fetch_data.py` once first (see above).

- **Mac:** double-click `Start CloudPeel.command`. The first time, macOS may
  block it; right-click it, choose **Open**, then **Open** again.
- **Windows:** double-click `Start CloudPeel.bat`.
- **Anything else:** `python3 -m http.server 8765 -d site`, then open
  <http://localhost:8765>.

The start files pick a free port, open the browser and keep running until
their window is closed. Leaflet and the QR-code library are bundled in
`site/vendor/`, so everything works without internet except the street-map
background (the page says so when it can't load).

`tools/record_demo.sh` records a 30-second video of the tour
(`media/cloudpeel_demo.mp4`, not kept in git) as a backup for live demos. It
needs Google Chrome, Node 22+ and macOS. It drives a hidden Chrome window through a scripted
tour (`tools/record_demo.mjs`) and encodes the frames with AVFoundation
(`tools/encode_mp4.swift`).

## Quick start

You need a Python environment with the pipeline's requirements installed
(OpenCV < 4.11) and a region that has been through Steps 2-3. The
pipeline's Sentinel-2 demo produces one. From `examples/cloudpeel/`:

```bash
python ../sentinel2_demo/run_demo.py --workdir work/demo
```

Then precompute the results and serve the site:

```bash
python precompute.py --region-dir work/demo/step4 --out site/data/taichung
python -m http.server 8765 -d site
```

The scripts use the pipeline in this repository; pass `--pipeline` to use
another clone.

Open <http://localhost:8765>. The 25 Step 4 runs take about 3 minutes on a laptop.

## Features

- **Before/after swipe** with a short "peel" sweep on load. The divider can be
  dragged, or focused and moved with the arrow keys (Shift for bigger steps).
- **Settings**: cloud tolerance and SSIM sliders, presets, a grid of every setting.
- **Real dates**: which three dates make up the mosaic, and which dates fill it.
- **How it works**: a four-step tour on the map (strips → seamlines → cloud
  masks → filling), using the region's own data.
- **Which date filled each patch**: colours by source date; click a patch for
  its date. `extras.py` reads this from Step 4's `fill_log.csv`, whose rows carry
  each patch's bounds (pipeline after PR #61). Where the log cannot decide, for
  example where one filled area touches patches filled from different dates, it
  falls back to matching the patch's texture (image gradients) against the
  candidates. Poisson blending keeps the source's gradients, so the true source
  matches at about 1.00.
- **Compare: paste without blending**: the same patches pasted straight in, to
  show what Poisson blending does. Blending roughly halves the colour step at
  patch edges, but with same-season fill dates the naive paste is often close;
  "Show the clearest example" jumps to the Taichung (auto) spot where the
  difference is easiest to see. Near the outer edge of the mosaic, blending can
  pull in the black no-data border and leave dark smudges.
- **Sharp zoom**: from zoom 13 the starting setting switches to 10 m views,
  pan-sharpened from the pipeline's XS and Pan mosaics.
- **Shareable links**: the address bar keeps the region, settings, divider,
  map view and layers.
- **Embed mode**: add `?embed=1` for a map-only view with a small region bar,
  for example in an `<iframe>` on another site.
- Seamline and cloud-mask layers, a "Suggest a place" form, works on phones.
- **Languages**: English, Traditional Chinese and Dutch (EN | 中文 | NL at the top).
  The first visit follows the browser language, the choice is remembered, and links
  carry it (`lang=zh`). All interface text is in `site/i18n.js`; region and
  pool names are translated there too. Names, the paper citation and the GitHub
  suggestion text stay in English. The translations were not written by native
  speakers, so have a native speaker check them before launch.

The dates, fill sources, naive paste, 10 m views and the walkthrough's strip
image come from `extras.py`, which runs after `precompute.py` and `seams.py`:

```bash
python extras.py --region-dir work/utrecht/step4 --step2-dir work/utrecht/step2 \
    --dates work/utrecht/region.json --out site/data/utrecht
```

## Adding a region

`make_region.py` prepares any land area from a point. It searches Earth Search
for Sentinel-2 L2A dates that cover a 22 km x 22 km box around the point, then
checks each date's cloud over the box from its 60 m scene classification. It
picks three partly cloudy dates to mosaic, plus clear and partly cloudy fill
candidates, and runs Steps 2-4 through the pipeline's own demo code (only the
grid, area and dates change):

```bash
python make_region.py --lat 52.0855 --lon 5.1735 --crs EPSG:32631 \
    --start 2024-03-15 --end 2024-10-15 --target-cloud 0.15 \
    --workdir work/utrecht
python precompute.py --region-dir work/utrecht/step4 \
    --out site/data/utrecht --name "Utrecht, Netherlands" --label "6 candidate dates"
```

Use a metric CRS for the area, such as its UTM zone. One region takes about
10-15 minutes and ~300 MB of working space in `work/`. Tips:
- Lower `--target-cloud` (0.1-0.2) for areas with scattered cumulus. With
  the 200 m cloud-mask buffer, many small clouds merge into large patches. Step 4
  skips patches that touch the mosaic edge, so very cloudy mosaic dates fill
  poorly.
- The land/sea mask is all land, so choose inland areas (or supply a real mask).

As in the demo, the middle strip is `a0000001`. Step 2 starts from the scene
whose name sorts first, so the mosaic grows from the centre. Working folders
made by older versions of `make_region.py` name the west strip `a0000001`, and
`--reuse` warns about them. Run such a region again without `--reuse` to start
from the middle strip.

### Place suggestions

Visitors can suggest a place with the form on the page. It opens a pre-filled
GitHub issue on this repository with the place, a map link, the season,
their note and a ready-to-run `make_region.py` command (UTM zone filled in).
Their titles start with "CloudPeel place suggestion"; change
`SUGGEST_ISSUE_URL` in `site/app.js` to send suggestions somewhere else. To add a
suggested place, run the command from the issue, then `precompute.py` and
`seams.py`, and check the result before publishing it. Very cloudy places,
coasts and boxes on a Sentinel-2 tile edge may need a different date range or
a nudged point.

`add_candidates.py` adds more dates to an existing region's candidate pool,
which is how the Taichung "+ 3 cloudier dates" pool was made.

## How it works

`precompute.py`, for each `(cloud_tolerance, ssim_threshold)` pair:

1. makes a temporary Step 4 folder from the region's `*_raw.tif` mosaics
   (candidate scenes and masks are linked, not copied);
2. writes `para_cld.txt` with that pair and runs `step4cloud_removal.py`;
3. reads the patch count from the log and the cloud left from
   `mosaic_cloudmask.tif`;
4. reprojects the RGB mosaic and the cloud mask to Web Mercator and saves them as
   PNGs. All images use one 2-98% stretch, taken from the before mosaic, so
   their colours can be compared.

Pass `--default-tolerance` / `--default-ssim` to choose the setting the page
starts on for that result set (Utrecht starts at tolerance 0.05, which fills the
same 95% without copying any cloud in).

After editing `site/app.js` or `site/style.css`, update the `?v=` tag on their
links in `site/index.html` (for example to the first 8 characters of
`cat site/app.js site/style.css | shasum`), so browsers fetch the new files.

Everything goes into `site/data/<region>/` (`manifest.json` + `img/`).
Pass `--tolerances` / `--ssims` for a different grid, or `--keep-runs` to keep
the GeoTIFFs.

## Regions

| Region (Utrecht loads first) | Pool | Cloudy area filled (default 0.25 / 0.75) | Cloud copied in |
|---|---|---|---|
| Taichung (pipeline demo) | 3 clear dates | 76% | 4.6 km² |
| Taichung (pipeline demo) | + 3 cloudier dates | 76% (different candidates win) | 4.6 km² |
| Taichung | less cloudy dates, picked per strip | 68% of a smaller cloud area (26 km² left vs 29) | 0 |
| Columbus, Ohio (OSU) | 6 dates, summer 2023 | 78% | 0 |
| Utrecht, Netherlands | 6 dates, 2024 | 95% | 6.1 km² |
| Nijmegen, Netherlands | 6 dates, 2024 | 81% | 0.3 km² |
| Taipei (Taipei 101) | 6 dates, 2023-24 | 81% | 0 |

What the settings do:
- **SSIM threshold** decides how many patches get filled.
- **Cloud tolerance** decides which candidates may be used. At 0.05,
  candidates whose own mask is cloudy over a patch are rejected, so no cloud is
  copied in. From 0.15 up, such candidates can win, which fills a patch with
  pixels their mask marks as cloud ("cloud copied in"). "% filled" alone doesn't
  show this, so the page reports it separately and dots it in the grid.
- Patches that touch the mosaic edge are skipped by Step 4, so a big cloud deck
  at the edge stays. `make_region.py` therefore picks each strip's date by the
  cloud **inside that strip**.

Colour: Step 1 (ERDAS IMAGINE) is not available, so `make_region.py` uses a
simple stand-in (`color_balance.py`). It matches each strip's per-band mean
and standard deviation to the clearest candidate date over pixels clear in
both, and removes most haze and illumination differences (`--no-color-balance`
turns it off). The two original Taichung demo pools are left as the pipeline's
demo makes them.

Known limitations: Haze that Sentinel-2's scene classification misses
is not masked. Mixing summer and winter dates made Step 2's seamline search fail
once (no path), so keep a region's dates within one season.

## Publishing

The documentation website's workflow (`.github/workflows/site.yml`) also
publishes CloudPeel at `cloudpeel/` on the same site: it copies `site/`,
downloads the release's images into `cloudpeel/data/`, and deploys both with the
documentation. To publish new or changed regions, add a new image archive to the
existing release as described in `fetch_data.py` and change its `ASSET`. Do not
create a new release for it: every published release of this repository is
archived on Zenodo as a new software version.

## Layout

```
fetch_data.py        downloads the precomputed images into site/data/
make_region.py       prepares a region from a point (Sentinel-2 dates, Steps 2-4)
color_balance.py     simple stand-in for Step 1
add_candidates.py    adds dates to a region's candidate pool
precompute.py        runs Step 4 over the parameter grid and renders the quicklooks
seams.py             seamline layer
extras.py            dates, fill sources, naive paste, 10 m views, strips
site/index.html      page
site/app.js          map, swipe, controls
site/i18n.js         interface text (English, Traditional Chinese, Dutch)
site/style.css       styles (light and dark)
site/vendor/         Leaflet and qrcodejs, bundled
site/data/           precomputed results (from fetch_data.py; not in git)
tools/               backup-video recorder
```

## Credits

The page shows the BuckAI Observatory and CSRSR (National Central University)
logos and a QR code for Amy's website. The QR code is drawn in the browser with
qrcodejs, so the link is never sent to a QR service.

Imagery: Copernicus Sentinel-2 L2A, from the Earth Search STAC catalogue.
Basemap: © OpenStreetMap contributors. Method: Hsu, H.-J., Tseng, K.-H., Tsai,
F., Liu, C.-L., Lo, C.-C., & Moortgat, J. (2026), *Applied Computing and
Geosciences*, 31, 100387, https://doi.org/10.1016/j.acags.2026.100387.
