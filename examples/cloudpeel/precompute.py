"""Precompute cloud-removal results for the website.

Takes a region that has already been through Steps 2-3 of the pipeline (for
example the Sentinel-2 demo's ``step4`` folder) and re-runs Step 4 for every
combination of ``cloud_tolerance`` and ``ssim_threshold`` in a grid. Each run
is rendered to web-ready PNG quicklooks (reprojected to Web Mercator) and a
JSON manifest with fill statistics, which the static page in ``site/`` reads.

Usage:
    python precompute.py --region-dir ../demo_output/step4 \
        --out site/data/taichung
"""
import argparse
import itertools
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

REPO = pathlib.Path(__file__).resolve().parents[2]  # the pipeline repository

WEB_CRS = "EPSG:3857"
DEFAULT_TOLERANCES = [0.05, 0.15, 0.25, 0.40, 0.60]
DEFAULT_SSIMS = [0.55, 0.65, 0.75, 0.85, 0.95]
# Files Step 4 needs that it does not modify (linked into each run folder).
SHARED = ["cloud_database", "cloud_masks", "raw_pan", "land_sea_mask.tif"]
# Small files copied into each run folder.
COPIED = ["allWindow.npy", "transform.npy", "ProcessOrder.txt"]
# Pre-Step-4 mosaics; copied to the names Step 4 reads and overwrites.
MOSAICS = ["mosaic_xs", "mosaic_pan", "mosaic_cloudmask"]


def key(tol, ssim):
    return f"t{tol:.2f}_s{ssim:.2f}"


def _link_file(src, dst):
    """Hard-link one file (no extra disk space, no special rights); copy if that fails."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def share(src, dst):
    """Make a SHARED input available in a run folder.

    A symlink where the system allows it; otherwise (for example on Windows
    without Developer Mode or administrator rights) hard links to the same
    files, or copies. Step 4 only reads these inputs, so all three are the same
    to it.
    """
    try:
        os.symlink(src, dst)
    except OSError:
        if pathlib.Path(src).is_dir():
            shutil.copytree(src, dst, copy_function=_link_file)
        else:
            _link_file(src, dst)


def prepare_run_dir(region, run_dir, tol, ssim):
    run_dir.mkdir(parents=True)
    for name in SHARED:
        share(region / name, run_dir / name)
    for name in COPIED:
        shutil.copy(region / name, run_dir / name)
    for name in MOSAICS:
        shutil.copy(region / f"{name}_raw.tif", run_dir / f"{name}.tif")
    (run_dir / "cldDatabase").mkdir()
    para = json.loads((region / "para_cld.txt").read_text())
    para.update({
        "CandiImgPath": str(run_dir / "cloud_database"),
        "CldMaskPath": str(run_dir / "cldDatabase"),
        "MosaicImgAddress": str(run_dir / "mosaic_xs.tif"),
        "MosaicCldAddress": str(run_dir / "mosaic_cloudmask.tif"),
        "PanMosaicImgAddress": str(run_dir / "mosaic_pan.tif"),
        "seaBorderAddress": str(run_dir / "land_sea_mask.tif"),
        "PanImgAddress": str(run_dir / "raw_pan"),
        "cloud_tolerance": str(tol),
        "ssim_threshold": str(ssim),
    })
    (run_dir / "para_cld.txt").write_text(json.dumps(para, indent=1))


def run_step4(pipeline, run_dir):
    script = pipeline / "step4_cloud_removal" / "step4cloud_removal.py"
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, str(script)], cwd=run_dir,
                          capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"Step 4 failed in {run_dir}:\n{proc.stderr[-2000:]}")
    m = re.search(r"(\d+)\s*/\s*(\d+)\s+reconstructions", proc.stdout)
    filled, total = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    return filled, total, elapsed


MASK_FILL = 255  # mask value outside the mosaic grid after reprojection


def warp_to_web(src_path, resampling, bands=None, is_mask=False):
    """Reproject a raster to Web Mercator; return (array, lat/lon bounds).

    Imagery treats 0 as nodata. Masks keep 0 as a valid (clear) value and get
    MASK_FILL outside the grid. Without a source nodata value, GDAL would nudge
    valid pixels equal to the destination nodata to 1, which for a mask means
    "cloud".
    """
    src_nodata, dst_nodata = (None, MASK_FILL) if is_mask else (0, 0)
    with rasterio.open(src_path) as src:
        bands = bands or list(range(1, src.count + 1))
        transform, width, height = calculate_default_transform(
            src.crs, WEB_CRS, src.width, src.height, *src.bounds)
        out = np.full((len(bands), height, width), dst_nodata, dtype=src.dtypes[0])
        for i, b in enumerate(bands):
            reproject(rasterio.band(src, b), out[i], dst_transform=transform,
                      dst_crs=WEB_CRS, resampling=resampling,
                      src_nodata=src_nodata, dst_nodata=dst_nodata)
        left, top = transform * (0, 0)
        right, bottom = transform * (width, height)
        w, s, e, n = transform_bounds(WEB_CRS, "EPSG:4326", left, bottom, right, top)
    return out, [[s, w], [n, e]]


def stretch_limits(rgb):
    valid = np.all(rgb > 0, axis=0)
    return [tuple(np.percentile(band[valid], [2, 98])) for band in rgb]


def save_rgb(rgb, limits, path):
    valid = np.all(rgb > 0, axis=0)
    out = np.zeros(rgb.shape[1:] + (4,), dtype=np.uint8)
    for i, (lo, hi) in enumerate(limits):
        out[..., i] = np.clip((rgb[i].astype(float) - lo) / (hi - lo) * 255, 0, 255)
    out[..., 3] = np.where(valid, 255, 0)
    Image.fromarray(out, "RGBA").save(path, optimize=True)


def save_mask_overlay(raw_mask, final_mask, path):
    """Red = cloud left unfilled, cyan = filled, amber = flagged by the candidate's mask."""
    out = np.zeros(raw_mask.shape + (4,), dtype=np.uint8)
    cloudy = raw_mask == 1
    out[cloudy & (final_mask == 0)] = (0, 220, 255, 150)
    out[final_mask == 1] = (255, 40, 40, 170)
    out[(final_mask >= 10) & (final_mask != MASK_FILL)] = (255, 180, 0, 170)
    Image.fromarray(out, "RGBA").save(path, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region-dir", type=pathlib.Path, required=True,
                        help="Step 4 folder with *_raw.tif mosaics and candidate scenes")
    parser.add_argument("--pipeline", type=pathlib.Path, default=REPO,
                        help="Clone of the cloud-removal pipeline (default: this repository)")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--name", default="Taichung, Taiwan (Sentinel-2 demo)")
    parser.add_argument("--label", default=None,
                        help="Short name of this candidate pool, shown as a choice on the page")
    parser.add_argument("--tolerances", type=float, nargs="+", default=DEFAULT_TOLERANCES)
    parser.add_argument("--ssims", type=float, nargs="+", default=DEFAULT_SSIMS)
    parser.add_argument("--default-tolerance", type=float, default=0.25,
                        help="Setting the page starts on for this result set")
    parser.add_argument("--default-ssim", type=float, default=0.75)
    parser.add_argument("--keep-runs", action="store_true",
                        help="Keep each run's GeoTIFFs in OUT/runs")
    args = parser.parse_args()
    region, pipeline = args.region_dir.resolve(), args.pipeline.resolve()
    out = args.out.resolve()
    (out / "img").mkdir(parents=True, exist_ok=True)

    # The "before" image and the stretch shared by every run.
    raw_rgb, bounds = warp_to_web(region / "mosaic_xs_raw.tif", Resampling.bilinear, [3, 2, 1])
    limits = stretch_limits(raw_rgb)
    save_rgb(raw_rgb, limits, out / "img" / "before.png")
    raw_mask, _ = warp_to_web(region / "mosaic_cloudmask_raw.tif", Resampling.nearest, is_mask=True)
    raw_mask = raw_mask[0]
    save_mask_overlay(raw_mask, raw_mask, out / "img" / "clouds_before.png")
    with rasterio.open(region / "mosaic_cloudmask_raw.tif") as src:
        native_raw_mask = src.read(1)
        px_area_km2 = abs(src.res[0] * src.res[1]) / 1e6
    cloudy_px = int((native_raw_mask == 1).sum())

    runs = {}
    with tempfile.TemporaryDirectory(prefix="cfw_") as tmp:
        for tol, ssim in itertools.product(args.tolerances, args.ssims):
            k = key(tol, ssim)
            run_dir = pathlib.Path(tmp) / k
            prepare_run_dir(region, run_dir, tol, ssim)
            filled, total, elapsed = run_step4(pipeline, run_dir)
            with rasterio.open(run_dir / "mosaic_cloudmask.tif") as src:
                final_native = src.read(1)
            left_px = int((final_native == 1).sum())
            flagged_px = int((final_native >= 10).sum())
            # An already-clear input has no cloud area left to fill.
            filled_fraction = 1 - left_px / cloudy_px if cloudy_px else 1.0
            rgb, _ = warp_to_web(run_dir / "mosaic_xs.tif", Resampling.bilinear, [3, 2, 1])
            save_rgb(rgb, limits, out / "img" / f"after_{k}.png")
            final_mask, _ = warp_to_web(run_dir / "mosaic_cloudmask.tif", Resampling.nearest, is_mask=True)
            save_mask_overlay(raw_mask, final_mask[0], out / "img" / f"clouds_{k}.png")
            runs[k] = {
                "cloud_tolerance": tol, "ssim_threshold": ssim,
                "patches_filled": filled, "patches_total": total,
                "cloudy_area_filled_pct": round(100 * filled_fraction, 1),
                "cloud_left_km2": round(left_px * px_area_km2, 2),
                "flagged_km2": round(flagged_px * px_area_km2, 2),
                "step4_seconds": round(elapsed, 1),
            }
            print(f"{k}: {filled}/{total} patches, "
                  f"{runs[k]['cloudy_area_filled_pct']}% of cloudy area, "
                  f"{runs[k]['flagged_km2']} km2 flagged, {elapsed:.1f} s")
            if args.keep_runs:
                dst = out / "runs" / k
                dst.mkdir(parents=True, exist_ok=True)
                for name in MOSAICS:
                    shutil.copy(run_dir / f"{name}.tif", dst)
            shutil.rmtree(run_dir)

    candidates = sorted(p.stem for p in (region / "cloud_database").glob("*.img"))
    label = args.label or f"{len(candidates)} candidate scenes"
    manifest = {
        "name": args.name,
        "label": label,
        "candidates": candidates,
        "bounds": bounds,
        "cloudy_km2_before": round(cloudy_px * px_area_km2, 2),
        "tolerances": args.tolerances,
        "ssims": args.ssims,
        "defaults": {"cloud_tolerance": args.default_tolerance, "ssim_threshold": args.default_ssim},
        "runs": runs,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    # Register this result set in the list of choices the page offers.
    index_path = out.parent / "datasets.json"
    datasets = json.loads(index_path.read_text()) if index_path.exists() else []
    entry = {"id": out.name, "region": args.name, "label": label, "path": f"data/{out.name}/"}
    datasets = [d for d in datasets if d["id"] != out.name] + [entry]
    index_path.write_text(json.dumps(datasets, indent=1))
    print(f"Wrote {len(runs)} runs to {out}")


if __name__ == "__main__":
    main()
