"""Extra layers for one result set: dates, fill sources, naive paste, 10 m views, strips.

Run after ``precompute.py`` (and ``seams.py``). For the result set's starting
setting (``manifest.defaults``) it reruns Step 4 once and adds:

- ``dates``: the acquisition date of every mosaicked strip and fill candidate;
- ``img/sources.png`` plus ``patches`` in the manifest: which candidate date
  filled each cloud patch, read from Step 4's ``fill_log.csv`` (its rows carry
  the patch bounds). Where the log cannot decide (a filled area overlaps
  patches filled from different dates, or the pipeline is older than the log),
  the source is inferred by comparing the texture (image gradients) of the
  patch with the candidates. Poisson blending keeps the source's gradients, so
  the best correlation identifies it. Each patch records ``how`` ("log" with
  Step 4's SSIM, or "texture" with the correlation ``score``);
- ``img/naive.png``: the same patches pasted straight from that candidate
  without blending, to show what Poisson blending fixes;
- ``img/before_10m.png`` and ``img/after10m_<key>.png``: 10 m views,
  pan-sharpened (Brovey) from the pipeline's 20 m XS and 10 m Pan mosaics;
- ``img/strips.png``: the three strips before mosaicking, for the walkthrough.

Usage:
    python extras.py --region-dir work/utrecht/step4 --step2-dir work/utrecht/step2 \
        --dates work/utrecht/region.json \
        --out site/data/utrecht
"""
import argparse
import csv
import json
import pathlib
import re
import tempfile

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import from_bounds
from scipy import ndimage

from add_candidates import load_demo
from precompute import key, prepare_run_dir, run_step4, save_rgb

REPO = pathlib.Path(__file__).resolve().parents[2]  # the pipeline repository

WEB = "EPSG:3857"
STRIP_COLOURS = [(255, 99, 71), (65, 160, 255), (255, 200, 40)]


def item_date(item_id):
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_", item_id)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def load_dates(spec, pipeline):
    """Scene name -> date, and the mosaicked strips from west to east.

    Both come from a region.json or the demo. The strips keep the order of its
    ``primary`` list (the demo's ``PRIMARY``), which runs west to east. Their
    names do not: the middle strip is ``a0000001`` so that Step 2 starts there.
    """
    if spec == "demo":
        demo = load_demo(pipeline)
        primary, candidates = demo.PRIMARY, demo.CANDIDATES
    else:
        region = json.loads(pathlib.Path(spec).read_text())
        primary, candidates = region["primary"], region["candidates"]
    dates = {n: item_date(i) for n, i, _ in list(primary) + list(candidates)}
    return dates, [n for n, _, _ in primary]


def web_grid(path):
    with rasterio.open(path) as src:
        t, w, h = calculate_default_transform(src.crs, WEB, src.width, src.height, *src.bounds)
        return src.crs, t, w, h


def to_web(array, src_transform, src_crs, grid, resampling, fill=0):
    _, t, w, h = grid
    bands = array if array.ndim == 3 else array[None]
    out = np.full((bands.shape[0], h, w), fill, dtype=bands.dtype)
    for b in range(bands.shape[0]):
        reproject(bands[b], out[b], src_transform=src_transform, src_crs=src_crs,
                  dst_transform=t, dst_crs=WEB, resampling=resampling,
                  src_nodata=fill, dst_nodata=fill)  # without src_nodata GDAL turns valid 0s into 1s
    return out


def limits_from_before(region, grid):
    """The 2-98% stretch precompute.py used (taken from the before mosaic)."""
    with rasterio.open(region / "mosaic_xs_raw.tif") as src:
        rgb = to_web(src.read([3, 2, 1]), src.transform, src.crs, grid, Resampling.bilinear)
    valid = np.all(rgb > 0, axis=0)
    return [tuple(np.percentile(b[valid], [2, 98])) for b in rgb]


def gradients(img):
    a = img.astype(np.float32)
    return ndimage.sobel(a, 0), ndimage.sobel(a, 1)


def read_fill_log(path, transform, shape):
    """Filled rows of Step 4's fill_log.csv as (candidate, ssim, row0, row1, col0, col1).

    Rows are placed on the mosaic grid (*transform*, *shape*) from their
    ``x_min``..``y_max`` bounds. Returns None if there is no log, or if it has no
    bounds (pipelines before the bounds were added).
    """
    if not path.exists():
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if rows and "x_min" not in rows[0]:
        return None
    inv = ~transform
    out = []
    for r in rows:
        if r["filled"] != "yes":
            continue
        c0, r0 = inv * (float(r["x_min"]), float(r["y_max"]))
        c1, r1 = inv * (float(r["x_max"]), float(r["y_min"]))
        r0, r1 = max(0, int(round(r0))), min(shape[0], int(round(r1)))
        c0, c1 = max(0, int(round(c0))), min(shape[1], int(round(c1)))
        if r0 < r1 and c0 < c1:
            out.append((r["candidate"].removesuffix(".img"), float(r["ssim"]), r0, r1, c0, c1))
    return out


def fill_sources(raw_mask, final_mask, final_xs, cand_xs, logged=None, min_px=50):
    """Label filled patches and find the candidate that filled each.

    With *logged* rows (from :func:`read_fill_log`), a patch takes the
    candidate whose filled patch windows cover all of it, if exactly one
    candidate does. Patch windows are padded, so a neighbouring window of
    another date often overlaps the edge of a patch; that does not count.
    Other patches fall back to texture matching, limited to the logged
    candidates that touch them, if any.
    """
    filled = (raw_mask == 1) & (final_mask != 1)
    labels, n = ndimage.label(filled)
    fy, fx = gradients(final_xs[2])  # red band
    cgrads = {c: gradients(x[2]) for c, x in cand_xs.items()}
    patches = []
    for lab, sl in enumerate(ndimage.find_objects(labels), start=1):
        m = labels == lab
        allowed = cgrads
        if logged:
            sub = labels[sl] == lab
            hits, cover = {}, {}
            for cand, ssim, r0, r1, c0, c1 in logged:
                rr0, rr1 = max(r0, sl[0].start) - sl[0].start, min(r1, sl[0].stop) - sl[0].start
                cc0, cc1 = max(c0, sl[1].start) - sl[1].start, min(c1, sl[1].stop) - sl[1].start
                if rr0 < rr1 and cc0 < cc1 and sub[rr0:rr1, cc0:cc1].any():
                    hits.setdefault(cand, []).append(ssim)
                    cover.setdefault(cand, np.zeros(sub.shape, bool))[rr0:rr1, cc0:cc1] = True
            full = [c for c in hits if cover[c][sub].all()]
            if len(full) == 1:
                cand = full[0]
                patches.append({"label": lab, "candidate": cand, "how": "log",
                                "ssim": round(max(hits[cand]), 2), "pixels": int(m.sum())})
                continue
            if hits:
                allowed = {c: g for c, g in cgrads.items() if c in hits}
        inner = ndimage.binary_erosion(m, iterations=2)
        if inner.sum() < min_px:
            continue
        best = (None, -1.0)
        for c, (cy, cx) in allowed.items():
            if np.any(cand_xs[c][2][inner] == 0):
                continue
            a = np.concatenate([fy[inner], fx[inner]])
            b = np.concatenate([cy[inner], cx[inner]])
            if a.std() == 0 or b.std() == 0:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            if r > best[1]:
                best = (c, r)
        if best[0]:
            patches.append({"label": lab, "candidate": best[0], "how": "texture",
                            "score": round(best[1], 2), "pixels": int(m.sum())})
    return labels, patches


def pansharpen(xs, pan, xs_t, pan_t, crs):
    """Brovey pan-sharpening of RGB (bands 3,2,1) to the Pan grid."""
    h, w = pan.shape
    up = np.zeros((3, h, w), np.float32)
    for i, b in enumerate([2, 1, 0]):
        reproject(xs[b].astype(np.float32), up[i], src_transform=xs_t, src_crs=crs,
                  dst_transform=pan_t, dst_crs=crs, resampling=Resampling.bilinear,
                  src_nodata=0, dst_nodata=0)
    intensity = up.mean(axis=0)
    ratio = np.where(intensity > 0, pan.astype(np.float32) / np.maximum(intensity, 1), 0)
    out = np.clip(up * ratio, 0, 65535).astype(np.uint16)
    out[:, (pan == 0) | (intensity == 0)] = 0
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region-dir", type=pathlib.Path, required=True)
    ap.add_argument("--step2-dir", type=pathlib.Path, required=True)
    ap.add_argument("--dates", required=True, help="region.json path, or 'demo'")
    ap.add_argument("--added", type=pathlib.Path, help="added.json from add_candidates.py")
    ap.add_argument("--pipeline", type=pathlib.Path, default=REPO,
                    help="Clone of the cloud-removal pipeline (default: this repository)")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    region, out = args.region_dir.resolve(), args.out.resolve()
    pipeline = args.pipeline.resolve()
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    d = manifest["defaults"]
    tol, ssim = d["cloud_tolerance"], d["ssim_threshold"]
    k = key(tol, ssim)

    # ---- Dates ----
    dates, strips = load_dates(args.dates, pipeline)
    if args.added and args.added.exists():
        dates.update({n: item_date(i) for n, i in json.loads(args.added.read_text()).items()})
    manifest["dates"] = {
        "mosaic": [{"scene": n, "date": dates[n]} for n in strips],
        "candidates": [{"scene": c, "date": dates.get(c)} for c in manifest["candidates"]],
    }

    grid = web_grid(region / "mosaic_xs_raw.tif")
    crs, t, w, h = grid
    limits = limits_from_before(region, grid)

    with tempfile.TemporaryDirectory(prefix="cfx_") as tmp:
        run_dir = pathlib.Path(tmp) / k
        prepare_run_dir(region, run_dir, tol, ssim)
        run_step4(pipeline, run_dir)
        with rasterio.open(run_dir / "mosaic_xs.tif") as src:
            final_xs, xs_t, xs_crs, bounds = src.read(), src.transform, src.crs, src.bounds
        with rasterio.open(run_dir / "mosaic_cloudmask.tif") as src:
            final_mask = src.read(1)
        with rasterio.open(run_dir / "mosaic_pan.tif") as src:
            final_pan, pan_t = src.read(1), src.transform
        logged = read_fill_log(run_dir / "fill_log.csv", xs_t, final_mask.shape)
    with rasterio.open(region / "mosaic_xs_raw.tif") as src:
        raw_xs = src.read()
    with rasterio.open(region / "mosaic_cloudmask_raw.tif") as src:
        raw_mask = src.read(1)
    with rasterio.open(region / "mosaic_pan_raw.tif") as src:
        raw_pan = src.read(1)

    # Candidates on the mosaic grid.
    cand_xs = {}
    for c in manifest["candidates"]:
        with rasterio.open(region / "cloud_database" / f"{c}.img") as src:
            win = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
            cand_xs[c] = src.read(window=win, boundless=True, fill_value=0)

    # ---- Fill sources and naive paste ----
    # Sources are traced on each cloud patch's interior; the area Step 4 actually
    # replaced (including its ~300 m buffer) is every pixel it changed, each
    # assigned to the nearest traced patch.
    if logged is None:
        print("  no fill_log.csv with patch bounds; tracing every patch by texture")
    labels, patches = fill_sources(raw_mask, final_mask, final_xs, cand_xs, logged)
    cand_of_label = {p["label"]: manifest["candidates"].index(p["candidate"]) + 1 for p in patches}
    traced = np.isin(labels, list(cand_of_label)) if patches else np.zeros(labels.shape, bool)
    changed = np.any(final_xs != raw_xs, axis=0)
    source_idx = np.zeros(labels.shape, np.uint8)  # 0 = none, i+1 = candidate i
    naive = raw_xs.copy()
    if patches:
        _, (iy, ix) = ndimage.distance_transform_edt(~traced, return_indices=True)
        nearest = labels[iy, ix]
        lut = np.zeros(labels.max() + 1, np.uint8)
        for lab, ci in cand_of_label.items():
            lut[lab] = ci
        source_idx[changed] = lut[nearest[changed]]
        for p in patches:
            ci = cand_of_label[p["label"]]
            region_px = changed & (nearest == p["label"])
            p["pixels"] = int(region_px.sum())
            ok = region_px & np.all(cand_xs[p["candidate"]] > 0, axis=0)
            naive[:, ok] = cand_xs[p["candidate"]][:, ok]
    # Encode the candidate index in the red channel of a PNG (alpha 255 where filled).
    idx_web = to_web(source_idx, xs_t, xs_crs, grid, Resampling.nearest, fill=0)[0]
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 0] = idx_web
    rgba[..., 3] = np.where(idx_web > 0, 255, 0)
    Image.fromarray(rgba, "RGBA").save(out / "img" / "sources.png", optimize=True)
    naive_web = to_web(naive[[2, 1, 0]], xs_t, xs_crs, grid, Resampling.bilinear)
    save_rgb(naive_web, limits, out / "img" / "naive.png")
    by_cand = {}
    for p in patches:
        by_cand.setdefault(p["candidate"], []).append(p)
    manifest["fill_sources"] = {
        "setting": k,
        "candidates": manifest["candidates"],
        "patches": [{"candidate": p["candidate"], "date": dates.get(p["candidate"]), "how": p["how"],
                     **({"ssim": p["ssim"]} if p["how"] == "log" else {"score": p["score"]}),
                     "km2": round(p["pixels"] * 400 / 1e6, 2)} for p in patches],
    }

    # ---- 10 m pan-sharpened views ----
    pan_grid = web_grid(region / "mosaic_pan_raw.tif")
    for name, xs, pan in (("before_10m.png", raw_xs, raw_pan), (f"after10m_{k}.png", final_xs, final_pan)):
        sharp = pansharpen(xs, pan, xs_t, pan_t, xs_crs)
        web = to_web(sharp, pan_t, xs_crs, pan_grid, Resampling.bilinear)
        save_rgb(web, limits, out / "img" / name)
    manifest["hires"] = {"setting": k, "res_m": 10}

    # ---- Strips before mosaicking, tinted outlines ----
    canvas = np.zeros((h, w, 4), np.uint8)
    for colour, n in zip(STRIP_COLOURS, strips):
        with rasterio.open(args.step2_dir / f"{n}.img") as src:
            rgb = to_web(src.read([3, 2, 1]), src.transform, src.crs, grid, Resampling.bilinear)
        valid = np.all(rgb > 0, axis=0)
        img = np.zeros((h, w, 4), np.uint8)
        for i, (lo, hi) in enumerate(limits):
            img[..., i] = np.clip((rgb[i].astype(float) - lo) / (hi - lo) * 255, 0, 255)
        edge = valid & ~ndimage.binary_erosion(valid, iterations=3)
        img[edge, :3] = colour
        img[..., 3] = np.where(valid, 215, 0)
        a = img[..., 3:4] / 255.0
        canvas[..., :3] = (canvas[..., :3] * (1 - a) + img[..., :3] * a).astype(np.uint8)
        canvas[..., 3] = np.maximum(canvas[..., 3], img[..., 3])
    Image.fromarray(canvas, "RGBA").save(out / "img" / "strips.png", optimize=True)
    manifest["strip_colours"] = ["#%02x%02x%02x" % c for c in STRIP_COLOURS[:len(strips)]]

    manifest_path.write_text(json.dumps(manifest, indent=1))
    n_log = sum(p["how"] == "log" for p in patches)
    scores = [p["score"] for p in patches if p["how"] == "texture"]
    print(f"{out.name}: {len(patches)} filled patches, {n_log} from the fill log, "
          f"{len(scores)} by texture (median score {np.median(scores) if scores else 0:.2f}), "
          f"dates {[m['date'] for m in manifest['dates']['mosaic']]}")


if __name__ == "__main__":
    main()
