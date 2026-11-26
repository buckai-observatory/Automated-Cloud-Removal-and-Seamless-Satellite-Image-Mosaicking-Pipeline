"""CloudPeel names the middle strip a0000001, as the demo does, and lists strips west to east."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
CLOUDPEEL = REPO / "examples" / "cloudpeel"
OLD_NAMES = ["a0000001", "a0000003", "a0000005"]   # west, middle, east before this change
NEW_NAMES = ["a0000003", "a0000001", "a0000005"]   # west, middle, east, as in the demo


def load(name, monkeypatch):
    monkeypatch.syspath_prepend(str(CLOUDPEEL))
    spec = importlib.util.spec_from_file_location(f"cloudpeel_{name}", CLOUDPEEL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def item(date):
    return {"id": f"S2A_TEST_{date.replace('-', '')}_0_L2A",
            "properties": {"datetime": f"{date}T10:00:00Z"}}


class FakeDemo:
    """The parts of the demo module that select_and_download uses."""
    PRIMARY, CANDIDATES = [], []

    def footprint(self, x, y, w, h):
        return (x, y, w, h), None

    def inside(self, corners, aoi, res):
        n = round((aoi[2] - aoi[0]) / res)
        return np.ones((n, n), bool)

    def download(self, data):
        self.downloaded = data


def region_json(path, names):
    path.write_text(json.dumps({
        "primary": [[n, f"S2A_TEST_2024060{k}_0_L2A", [0, 0, 1, 1]] for k, n in enumerate(names, 1)],
        "candidates": [["a0000101", "S2A_TEST_20240610_0_L2A", [0, 0, 1, 1]]]}))
    return path


def test_new_region_names_the_middle_strip_a0000001(monkeypatch, tmp_path):
    make_region = load("make_region", monkeypatch)
    cloud = {"2024-06-01": 0.30, "2024-06-06": 0.25, "2024-06-11": 0.35,
             "2024-06-16": 0.0, "2024-06-21": 0.0, "2024-06-26": 0.01}
    items = [item(d) for d in cloud]
    monkeypatch.setattr(make_region, "search", lambda *args: items)

    def assess(demo, it):
        n = round(make_region.SIZE / 60)
        flags = np.zeros(n * n, bool)
        flags[:round(cloud[it["properties"]["datetime"][:10]] * n * n)] = True
        return np.ones((n, n), bool), flags.reshape(n, n)

    monkeypatch.setattr(make_region, "assess", assess)
    demo = FakeDemo()
    args = argparse.Namespace(lat=40.0, lon=-83.0, crs="EPSG:32617", start="2024-06-01",
                              end="2024-06-30", primary_cloud=[0.10, 0.60], target_cloud=0.30,
                              extra_cloudy=0, workdir=tmp_path)
    x0, y0 = 300000, 4400000
    aoi = (x0, y0, x0 + make_region.SIZE, y0 + make_region.SIZE)
    make_region.select_and_download(demo, args, aoi, None, x0, y0, tmp_path / "data")

    names = [n for n, _, _ in demo.PRIMARY]
    centres = [rect[0] for _, _, rect in demo.PRIMARY]
    assert centres == sorted(centres), "PRIMARY must stay in west-to-east order"
    assert names == NEW_NAMES
    middle = names[1]
    assert min(names) == middle == "a0000001", "Step 2 must start from the middle strip"
    saved = json.loads((tmp_path / "region.json").read_text())
    assert [n for n, _, _ in saved["primary"]] == NEW_NAMES


@pytest.mark.parametrize("names, warns", [(NEW_NAMES, False), (OLD_NAMES, True)])
def test_reuse_warns_when_the_west_strip_sorts_first(monkeypatch, tmp_path, capsys, names, warns):
    make_region = load("make_region", monkeypatch)
    demo = FakeDemo()
    aoi = (0, 0, 22000, 22000)
    make_region.load_region(region_json(tmp_path / "region.json", names), demo, aoi)

    assert [n for n, _, _ in demo.PRIMARY] == names
    assert demo.CANDIDATES == [("a0000101", "S2A_TEST_20240610_0_L2A", aoi)]
    err = capsys.readouterr().err
    assert ("names the west strip a0000001" in err) == warns
    assert ("without --reuse" in err) == warns


@pytest.mark.parametrize("names", [NEW_NAMES, OLD_NAMES])
def test_extras_lists_region_strips_west_to_east(monkeypatch, tmp_path, names):
    extras = load("extras", monkeypatch)
    dates, strips = extras.load_dates(str(region_json(tmp_path / "region.json", names)), REPO)
    assert strips == names
    assert dates == {names[0]: "2024-06-01", names[1]: "2024-06-02", names[2]: "2024-06-03",
                     "a0000101": "2024-06-10"}


def test_extras_lists_demo_strips_west_to_east(monkeypatch):
    extras = load("extras", monkeypatch)
    dates, strips = extras.load_dates("demo", REPO)
    demo = extras.load_demo(REPO)
    xs = {n: rect[0] for n, _, rect in demo.PRIMARY}
    assert [xs[n] for n in strips] == sorted(xs.values())
    assert strips[1] == min(strips) == "a0000001"
    assert set(strips) <= set(dates)
