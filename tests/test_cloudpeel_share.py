"""CloudPeel precompute works where symlinks are not allowed (Windows without
Developer Mode or administrator rights)."""
import importlib.util
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
pytest.importorskip("PIL")


@pytest.fixture(scope="module")
def precompute():
    spec = importlib.util.spec_from_file_location(
        "cloudpeel_precompute_share", ROOT / "examples" / "cloudpeel" / "precompute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path):
    region = tmp_path / "region"
    (region / "cloud_database").mkdir(parents=True)
    (region / "cloud_database" / "a0000101.img").write_bytes(b"xs")
    (region / "land_sea_mask.tif").write_bytes(b"mask")
    run = tmp_path / "run"
    run.mkdir()
    return region, run


def _no_symlinks(*args, **kwargs):
    raise OSError(1314, "A required privilege is not held by the client")


def test_shares_by_hard_link_when_symlinks_fail(precompute, inputs, monkeypatch):
    region, run = inputs
    monkeypatch.setattr(precompute.os, "symlink", _no_symlinks)
    precompute.share(region / "cloud_database", run / "cloud_database")
    precompute.share(region / "land_sea_mask.tif", run / "land_sea_mask.tif")
    shared = run / "cloud_database" / "a0000101.img"
    assert not (run / "cloud_database").is_symlink()
    assert shared.read_bytes() == b"xs"
    assert os.path.samefile(shared, region / "cloud_database" / "a0000101.img")
    assert os.path.samefile(run / "land_sea_mask.tif", region / "land_sea_mask.tif")


def test_copies_when_hard_links_fail_too(precompute, inputs, monkeypatch):
    region, run = inputs
    monkeypatch.setattr(precompute.os, "symlink", _no_symlinks)
    monkeypatch.setattr(precompute.os, "link", _no_symlinks)
    precompute.share(region / "cloud_database", run / "cloud_database")
    precompute.share(region / "land_sea_mask.tif", run / "land_sea_mask.tif")
    assert (run / "cloud_database" / "a0000101.img").read_bytes() == b"xs"
    assert (run / "land_sea_mask.tif").read_bytes() == b"mask"
    assert not os.path.samefile(run / "land_sea_mask.tif", region / "land_sea_mask.tif")
