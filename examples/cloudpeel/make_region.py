"""Prepare a new showcase region from a point on the map.

Picks Sentinel-2 L2A dates over a 22 km x 22 km area around a point and runs
Steps 2-4 of the pipeline there. The pipeline's Sentinel-2 demo does the work.
This script only changes the demo's area, grid and scene list, so the
conversion and the steps are exactly the demo's:

- three partly cloudy dates become the tilted strips that get mosaicked;
- the clearest dates, plus a few partly cloudy ones, become the
  cloud-filling candidates. The partly cloudy ones give ``cloud_tolerance``
  something to decide.

Dates are chosen from a quick look at each scene's scene classification layer
at 60 m. Run ``precompute.py`` on ``WORKDIR/step4`` afterwards.

Usage:
    python make_region.py --lat 40.0076 --lon -83.0300 --crs EPSG:32617 \
        --start 2024-05-01 --end 2024-09-30 --workdir work/columbus \
       
"""
import argparse
import datetime as dt
import json
import shutil
import pathlib
import sys
import urllib.parse
import urllib.request

import numpy as np
from pyproj import Transformer
from rasterio.enums import Resampling
from shapely.geometry import box, shape

from add_candidates import load_demo
from color_balance import balance

REPO = pathlib.Path(__file__).resolve().parents[2]  # the pipeline repository

SEARCH = "https://earth-search.aws.element84.com/v1/search"
SIZE = 22000  # metres, as in the demo
# Strip layout relative to the area's south-west corner, as in the demo, from
# west to east: (centre x offset, centre y offset, width, height)
STRIPS = [(5500, 11000, 8000, 18000), (10500, 11500, 8000, 16000), (15500, 10500, 8000, 17000)]
# Scene names of the strips, as in the demo. Step 2 starts from the scene whose
# name sorts first, so the middle strip is a0000001 and the mosaic grows from
# the centre.
STRIP_NAMES = ["a0000003", "a0000001", "a0000005"]


def search(aoi_ll, start, end):
    """Return covered acquisition dates across all STAC result pages."""
    body = {"collections": ["sentinel-2-l2a"], "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
            "intersects": box(*aoi_ll).__geo_interface__,
            "query": {"eo:cloud_cover": {"lt": 85}}, "limit": 200}
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(SEARCH, json.dumps(body).encode(), headers)
    items = []
    while True:
        with urllib.request.urlopen(req) as response:
            page = json.load(response)
            page_url = response.geturl()
        items.extend(page["features"])
        next_link = next((link for link in page.get("links", []) if link["rel"] == "next"), None)
        if next_link is None:
            break
        next_body = next_link.get("body")
        next_headers = dict(next_link.get("headers", {}))
        if next_link.get("merge", False):
            # STAC merges paging fields into the original search, not the previous page.
            next_body = {**body, **(next_body or {})}
            next_headers = {**headers, **next_headers}
        if next_body is not None and not any(name.lower() == "content-type" for name in next_headers):
            next_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            urllib.parse.urljoin(page_url, next_link["href"]),
            data=json.dumps(next_body).encode() if next_body is not None else None,
            headers=next_headers, method=next_link.get("method", "GET"),
        )
    area = box(*aoi_ll)
    # Keep scenes that cover the whole area, one per date.
    by_date = {}
    for it in items:
        if shape(it["geometry"]).contains(area):
            by_date.setdefault(it["properties"]["datetime"][:10], it)
    return [by_date[d] for d in sorted(by_date)]


def assess(demo, item):
    """Valid-data and cloud rasters over the area, from the 60 m SCL."""
    scl = demo.read_asset(item["assets"]["scl"]["href"], demo.AOI, 60.0, Resampling.nearest)
    valid = scl > 0
    return valid, np.isin(scl, demo.SCL_CLOUD) & valid


def fraction(cloud, where):
    return float(cloud[where].mean()) if where.any() else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--crs", required=True, help="Projected CRS in metres, e.g. a UTM zone")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--workdir", type=pathlib.Path, required=True)
    parser.add_argument("--pipeline", type=pathlib.Path, default=REPO,
                        help="Clone of the cloud-removal pipeline (default: this repository)")
    parser.add_argument("--primary-cloud", type=float, nargs=2, default=[0.10, 0.60],
                        help="Cloud range for the dates that get mosaicked")
    parser.add_argument("--target-cloud", type=float, default=0.30,
                        help="Preferred cloud fraction for the mosaicked dates. Lower gives smaller "
                             "patches, which Step 4 can fill; patches touching the edge are skipped")
    parser.add_argument("--reuse", action="store_true",
                        help="Reuse the dates and downloads in WORKDIR (region.json) and only rerun")
    parser.add_argument("--no-color-balance", action="store_true",
                        help="Mosaic the strips as delivered (no stand-in for Step 1)")
    parser.add_argument("--extra-cloudy", type=int, default=3,
                        help="Partly cloudy candidates to add to the clear ones")
    args = parser.parse_args()
    demo = load_demo(args.pipeline.resolve())

    # Area around the point, snapped to 1 km, in the chosen CRS.
    to_crs = Transformer.from_crs("EPSG:4326", args.crs, always_xy=True)
    to_ll = Transformer.from_crs(args.crs, "EPSG:4326", always_xy=True)
    cx, cy = to_crs.transform(args.lon, args.lat)
    x0, y0 = round((cx - SIZE / 2) / 1000) * 1000, round((cy - SIZE / 2) / 1000) * 1000
    aoi = (x0, y0, x0 + SIZE, y0 + SIZE)
    aoi_ll = to_ll.transform_bounds(*aoi)
    demo.CRS, demo.AOI = args.crs, aoi

    data = args.workdir / "data"
    if args.reuse:
        load_region(args.workdir / "region.json", demo, aoi)
    else:
        select_and_download(demo, args, aoi, aoi_ll, x0, y0, data)

    if not args.no_color_balance:
        # Stand-in for Step 1: balance the strips against the first (clearest,
        # closest in time) candidate.
        print("Colour-balancing the mosaic strips...")
        balance(data, [p[0] for p in demo.PRIMARY], demo.CANDIDATES[0][0],
                2 ** demo.TRUE_BITS - 1, demo.pan_name)
    sys.argv = ["run_demo.py", "--workdir", str(args.workdir), "--skip-download"]
    demo.main()


def load_region(path, demo, aoi):
    """Give the demo the dates recorded in a region.json (for --reuse)."""
    saved = json.loads(path.read_text())
    demo.PRIMARY = [(n, i, tuple(r)) for n, i, r in saved["primary"]]
    demo.CANDIDATES = [(n, i, aoi) for n, i, _ in saved["candidates"]]
    print("Reusing", [p[1] for p in demo.PRIMARY], "and", len(demo.CANDIDATES), "candidates")
    names = [p[0] for p in demo.PRIMARY]  # west to east
    if len(names) == len(STRIP_NAMES) and min(names) != names[1]:
        side = "west" if min(names) == names[0] else "east"
        print(f"Warning: {path} names the {side} strip {min(names)}. Step 2 starts from the "
              "scene whose name sorts first, so this run grows the mosaic from that strip, "
              "not from the middle one. Older versions of make_region.py named the west strip "
              "a0000001. To start from the middle strip, run without --reuse, which chooses "
              "and downloads the dates again.", file=sys.stderr)


def select_and_download(demo, args, aoi, aoi_ll, x0, y0, data):
    """Choose the dates, record them in region.json and download the scenes."""
    items = search(aoi_ll, args.start, args.end)
    print(f"{len(items)} dates cover the whole area; checking cloud over the area...")
    if not items:
        sys.exit("No Sentinel-2 tile covers the whole area (it may straddle a tile or "
                 "UTM-zone edge). Move the point a few km.")
    scored = []
    everywhere = np.ones((round(SIZE / 60), round(SIZE / 60)), bool)
    for it in items:
        valid, cloud = assess(demo, it)
        total = fraction(cloud, everywhere)
        print(f"  {it['id']}: data {valid.mean():.0%}, cloud {total:.0%}")
        if valid.mean() >= 0.99:
            scored.append((it, total, cloud))

    # Mosaic: for each strip, the date whose cloud *inside that strip* is in
    # --primary-cloud and closest to --target-cloud (or, failing that, the
    # least cloudy date). Choosing by the whole area can put a cloud deck that
    # sits over one corner into the strip that covers it.
    lo, hi = args.primary_cloud
    primary, used = [], set()
    for dx, dy, w, h in STRIPS:
        corners, _ = demo.footprint(x0 + dx, y0 + dy, w, h)
        strip = demo.inside(corners, aoi, 60.0)
        options = [(abs(c - args.target_cloud) if lo <= c <= hi else 10 + c, it, c)
                   for it, _, cl in scored if it["id"] not in used
                   for c in [fraction(cl, strip)]]
        _, it, c = min(options, key=lambda o: o[0])
        primary.append((it, c))
        used.add(it["id"])
    mid = np.mean([dt.date.fromisoformat(s[0]["properties"]["datetime"][:10]).toordinal() for s in primary])
    near = lambda s: abs(dt.date.fromisoformat(s[0]["properties"]["datetime"][:10]).toordinal() - mid)
    # Candidates: the three clear dates (<3% cloud) closest in time, plus partly cloudy ones.
    clear = sorted((s for s in scored if s[1] < 0.03 and s[0]["id"] not in used), key=near)[:3]
    if len(clear) < 2:
        sys.exit("Not enough clear dates; widen --start/--end.")
    extra = sorted((s for s in scored if 0.03 <= s[1] <= 0.8 and s[0]["id"] not in used),
                   key=near)[:args.extra_cloudy]

    demo.PRIMARY = [(name, s[0]["id"], (x0 + dx, y0 + dy, w, h))
                    for name, s, (dx, dy, w, h) in zip(STRIP_NAMES, primary, STRIPS)]
    demo.CANDIDATES = [(f"a{101 + 2 * i:07d}", s[0]["id"], aoi) for i, s in enumerate(clear + extra)]
    print("Mosaic (cloud inside each strip):", [(p[1], f"{c:.0%}") for p, (_, c) in zip(demo.PRIMARY, primary)])
    print("Candidates:", [(c[1], f"{s[1]:.0%}") for c, s in zip(demo.CANDIDATES, clear + extra)])

    args.workdir.mkdir(parents=True, exist_ok=True)
    (args.workdir / "region.json").write_text(json.dumps({
        "lat": args.lat, "lon": args.lon, "crs": args.crs, "aoi": aoi,
        "primary": demo.PRIMARY, "candidates": demo.CANDIDATES}, indent=1))
    for sub in ("scenes_original", "raw_pan_original"):
        shutil.rmtree(data / sub, ignore_errors=True)
    demo.download(data)


if __name__ == "__main__":
    main()
