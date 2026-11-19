"""Run Steps 2-4 end to end on tiny synthetic scenes (#21).

Three overlapping tilted strips are mosaicked; the middle one has a fake cloud,
and one clear candidate scene covers the whole area. The work folders and the
configuration files are those of the Sentinel-2 demo
(``examples/sentinel2_demo/run_demo.py``), so this also checks the layout the
demo and the README describe. The GDAL command-line tools are replaced by
rasterio equivalents, as in the other Step 2 and Step 3 tests, so the test
runs wherever the Python dependencies are installed.
"""
import ast
import importlib.util
import json
import pathlib

import numpy as np
import pytest
import rasterio
from rasterio.shutil import copy
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from scipy.ndimage import gaussian_filter

ROOT = pathlib.Path(__file__).resolve().parents[1]

# A 6 km x 6 km area: 300 x 300 XS pixels at 20 m, 600 x 600 Pan pixels at 10 m.
AOI = (200000, 2500000, 206000, 2506000)
PRIMARY = [
    ("a0000001", None, (201600, 2503000, 2400, 5000)),
    ("a0000003", None, (203000, 2503100, 2400, 4400)),
    ("a0000005", None, (204400, 2502900, 2400, 4700)),
]
CANDIDATES = [("a0000101", None, AOI)]
CLOUDY = "a0000003"
CLOUD_CENTRE, CLOUD_RADIUS = (203000, 2503100), 250   # metres


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location(
        "run_demo", ROOT / "examples" / "sentinel2_demo" / "run_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ground(bounds, res):
    """Smooth synthetic 12-bit ground (4 bands) on the grid of *bounds*, the same for every scene."""
    x0, y0, x1, y1 = AOI
    size = int(round((x1 - x0) / 10))
    field = gaussian_filter(np.random.default_rng(21).normal(size=(size, size)), 6)
    field = (field - field.min()) / (field.max() - field.min())
    # Cut *bounds* out of the 10 m field and average it to *res*.
    step = int(round(res / 10))
    c0, r0 = int(round((bounds[0] - x0) / 10)), int(round((y1 - bounds[3]) / 10))
    c1, r1 = int(round((bounds[2] - x0) / 10)), int(round((y1 - bounds[1]) / 10))
    cut = field[r0:r1, c0:c1]
    cut = cut.reshape(cut.shape[0] // step, step, cut.shape[1] // step, step).mean(axis=(1, 3))
    return np.stack([800 + 1600 * cut + 150 * band for band in range(4)])


def write_scene(demo, name, rect, xs_dir, mask_dir, pan_dir, brightness):
    """Write one scene in the demo's input layout (XS .img, cloud mask, Pan .tif)."""
    if rect == AOI:
        corners, bounds = None, AOI
    else:
        corners, bounds = demo.footprint(*rect)
    valid = demo.inside(corners, bounds, demo.XS_RES) if corners else True
    xs = np.clip(ground(bounds, demo.XS_RES) * brightness, 1, 4095).astype(np.uint16)

    transform, width, height = demo.grid(bounds, demo.XS_RES)
    cols, rows = np.meshgrid(np.arange(width), np.arange(height))
    x = transform.c + (cols + 0.5) * transform.a
    y = transform.f + (rows + 0.5) * transform.e
    cloud = np.zeros((height, width), bool)
    if name == CLOUDY:
        cloud = np.hypot(x - CLOUD_CENTRE[0], y - CLOUD_CENTRE[1]) < CLOUD_RADIUS
        xs[:, cloud] = 4000
    xs[:, ~valid] = 0
    demo.write(xs_dir / f"{name}.img", xs, bounds, demo.XS_RES, "HFA")
    demo.write(mask_dir / f"{name}_cloud.tif", np.where(cloud & valid, 255, 0).astype(np.uint8),
               bounds, demo.XS_RES, "GTiff")

    pan = np.clip(ground(bounds, demo.PAN_RES)[:3].mean(axis=0) * brightness, 1, 4095).astype(np.uint16)
    if corners:
        pan[~demo.inside(corners, bounds, demo.PAN_RES)] = 0
    demo.write(pan_dir / f"{demo.pan_name(name)}.tif", pan, bounds, demo.PAN_RES, "GTiff")
    return int(cloud.sum())


def clip_pan(src_path, dst_path, crs, bounds):
    """rasterio stand-in for Step 3's gdalwarp call (same grid: source resolution, -te bounds)."""
    x0, y0, x1, y1 = bounds
    with rasterio.open(src_path) as src:
        res = src.res[0]
        width, height = int(round((x1 - x0) / res)), int(round((y1 - y0) / res))
        with WarpedVRT(src, crs=crs, transform=from_origin(x0, y1, res, res),
                       width=width, height=height) as vrt:
            profile = dict(driver="GTiff", width=width, height=height, count=vrt.count,
                           dtype=vrt.dtypes[0], crs=vrt.crs, transform=vrt.transform)
            with rasterio.open(dst_path, "w", **profile) as dst:
                dst.write(vrt.read())


def test_steps_2_to_4_end_to_end(demo, step2, step3, step4, tmp_path, monkeypatch):
    for name, value in (("AOI", AOI), ("PRIMARY", PRIMARY), ("CANDIDATES", CANDIDATES)):
        monkeypatch.setattr(demo, name, value)
    monkeypatch.setattr(step2, "assign_crs_copy", lambda src, dst, crs: copy(src, dst, driver="GTiff"))
    monkeypatch.setattr(step3, "clip_pan", clip_pan)

    work = tmp_path / "work folder"
    data = work / "data"
    for sub in ("scenes", "candidates", "cloud_masks", "raw_pan"):
        (data / sub).mkdir(parents=True)
    for (name, _, rect), brightness in zip(PRIMARY, (1.0, 1.04, 0.97)):
        cloud_px = write_scene(demo, name, rect, data / "scenes", data / "cloud_masks", data / "raw_pan", brightness)
        assert (cloud_px > 0) == (name == CLOUDY)
    for name, _, rect in CANDIDATES:
        write_scene(demo, name, rect, data / "candidates", data / "cloud_masks", data / "raw_pan", 1.0)
    _, w, h = demo.grid(AOI, demo.XS_RES)
    demo.write(data / "land_sea_mask.tif", np.ones((h, w), np.uint8), AOI, demo.XS_RES, "GTiff")

    demo.set_up_steps(work, data)
    demo.write_configs(work)
    s2, s3, s4 = work / "step2", work / "step3", work / "step4"
    # The strips overlap by only ~1 km: search seamlines on a 40 m grid
    # instead of the demo's 100 m one.
    para = json.loads((s2 / "para.txt").read_text())
    (s2 / "para.txt").write_text(json.dumps({**para, "resampleTo": "2", "kernel": "5"}))

    # Step 2: seamline mosaic of the three strips
    monkeypatch.chdir(s2)
    step2.main()
    order = ast.literal_eval((s2 / "ProcessOrder.txt").read_text())
    assert sorted(order) == [f"{name}.img" for name, _, _ in PRIMARY]
    with rasterio.open(s2 / "mosaic_xs.tif") as src:
        xs = src.read()
        assert src.count == 4 and src.dtypes[0] == "uint16"
        assert src.crs.to_string() == demo.CRS
        assert src.nodata == 0  # area outside the scenes (#49)
    with rasterio.open(s2 / "mosaic_cloudmask.tif") as src:
        cloud_before = src.read(1) == 1
        assert src.nodata is None  # 0 means clear here, not no data
    assert np.all(xs > 0, axis=0).mean() > 0.5
    assert cloud_before.sum() > 0

    # Step 3: Pan mosaic along the Step 2 seamlines
    demo.copy_matching(s2, s3, ["transform.npy", "ImgInd.npy", "allWindow.npy", "Union_gt.npy",
                                "ProcessOrder.txt", "*_seamline_polygon.img",
                                "*_seamline_polygon.img.aux.xml"])
    monkeypatch.chdir(s3)
    step3.main()
    with rasterio.open(s3 / "mosaic_pan.tif") as src:
        pan = src.read(1)
        assert src.res == (demo.PAN_RES, demo.PAN_RES)
        assert src.nodata == 0
    # The Pan mosaic covers the same area as the XS mosaic.
    assert pan.shape == (xs.shape[1] * 2, xs.shape[2] * 2)
    footprint_pan = np.repeat(np.repeat(np.all(xs > 0, axis=0), 2, axis=0), 2, axis=1)
    assert np.mean(pan[footprint_pan] > 0) > 0.99

    # Step 4: fill the cloud from the candidate
    demo.copy_matching(s2, s4, ["mosaic_xs.tif", "mosaic_cloudmask.tif", "allWindow.npy",
                                "transform.npy", "ProcessOrder.txt"])
    demo.copy_matching(s3, s4, ["mosaic_pan.tif"])
    for f in ("mosaic_xs.tif", "mosaic_pan.tif", "mosaic_cloudmask.tif"):
        (s4 / f.replace(".tif", "_raw.tif")).write_bytes((s4 / f).read_bytes())
    monkeypatch.chdir(s4)
    step4.main()

    for name, nodata in (("mosaic_xs.tif", 0), ("mosaic_pan.tif", 0), ("mosaic_cloudmask.tif", None)):
        with rasterio.open(s4 / name) as src:
            assert src.nodata == nodata, name
    result = demo.check_results(s4)
    assert result["zero_pixels"] == 0
    assert result["fill_fraction"] > 0.9
    with rasterio.open(s4 / "mosaic_xs.tif") as src:
        filled = src.read()
    # The fake cloud (4000 in every band) is replaced by ground-like values.
    assert filled[:, cloud_before].max() < 3800
    assert (s4 / "fill_log.csv").read_text().count(",yes,") >= 1
