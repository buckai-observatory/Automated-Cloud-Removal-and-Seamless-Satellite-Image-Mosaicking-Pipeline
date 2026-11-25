"""Step 4 reports unexpected candidate failures and keeps trying alternatives."""
import csv
import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window


@pytest.fixture
def cloud_run(tmp_path, monkeypatch, step4):
    import os

    transform = from_origin(1000, 10000, 60, 60)
    mosaic = np.random.default_rng(15).integers(50, 180, (4, 64, 64), dtype=np.uint8)
    for folder in ("candidates", "cldDatabase", "masks", "pan"):
        (tmp_path / folder).mkdir()

    def write_raster(path, data, raster_transform=transform):
        if data.ndim == 2:
            data = data[None]
        with rasterio.open(tmp_path / path, "w", driver="GTiff", height=data.shape[1],
                           width=data.shape[2], count=data.shape[0], dtype=data.dtype,
                           crs="EPSG:3826", transform=raster_transform) as dst:
            dst.write(data)

    write_raster("mosaic_xs.tif", mosaic)
    write_raster("mosaic_pan.tif", mosaic[0])
    write_raster("land.tif", np.ones((64, 64), np.uint8))
    cloudmask = np.zeros((64, 64), np.uint8)
    cloudmask[20:30, 20:30] = 1
    write_raster("mosaic_cloudmask.tif", cloudmask)
    write_raster("candidates/A0000001.img", mosaic)
    windows = np.empty(1, dtype=object)
    windows[0] = Window(0, 0, 64, 64)
    np.save(tmp_path / "allWindow.npy", windows)
    np.save(tmp_path / "transform.npy", [[1000, 10000], [1000, 10000]])
    (tmp_path / "ProcessOrder.txt").write_text("primary_a.img,primary_b.img")
    (tmp_path / "para_cld.txt").write_text(json.dumps({
        "res": 60, "pan_res": 60, "trueBits": 8,
        "CandiImgPath": str(tmp_path / "candidates"),
        "CldMaskPath": str(tmp_path / "cldDatabase"),
        "MosaicImgAddress": str(tmp_path / "mosaic_xs.tif"),
        "MosaicCldAddress": str(tmp_path / "mosaic_cloudmask.tif"),
        "PanMosaicImgAddress": str(tmp_path / "mosaic_pan.tif"),
        "PanImgAddress": str(tmp_path / "pan"),
        "CandiMaskFolderName": "masks", "seaBorderAddress": str(tmp_path / "land.tif"),
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(step4, "listdir", lambda path: sorted(os.listdir(path)))
    return SimpleNamespace(root=tmp_path, mosaic=mosaic, write=write_raster)


def failures(caplog):
    return [record for record in caplog.records
            if record.name == "step4cloud_removal" and record.levelno >= logging.WARNING]


def test_scoring_failure_names_patch_candidate_and_error(step4, cloud_run, caplog):
    cloud_run.write("candidates/A0000001.img", cloud_run.mosaic[0])
    step4.main()
    records = failures(caplog)
    assert len(records) == 1
    assert "SSIM scoring" in records[0].message
    assert "1_cld.img" in records[0].message and "A0000001.img" in records[0].message
    assert records[0].exc_info[0] is IndexError


def test_unreadable_candidate_does_not_prevent_a_valid_fill(step4, cloud_run, caplog):
    (cloud_run.root / "candidates/A0000003.img").write_bytes(b"not a raster")
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    records = failures(caplog)
    # Reported once, when the candidates are listed, not once per cloud patch;
    # the unreadable scene is then left out of the scoring.
    assert len(records) == 1
    assert "A0000003.img cannot be opened and is skipped" in records[0].message
    with rasterio.open(cloud_run.root / "mosaic_cloudmask.tif") as result:
        assert np.all(result.read(1)[20:30, 20:30] == 0)


def test_missing_cloud_mask_is_reported(step4, cloud_run, caplog):
    step4.main()
    records = failures(caplog)
    assert len(records) == 1
    assert "Cloud filling" in records[0].message
    assert "1_cld.img" in records[0].message and "A0000001.img" in records[0].message
    assert records[0].exc_info[0] is FileNotFoundError
    assert "candidate cloud mask" in str(records[0].exc_info[1])


def test_fill_failure_continues_to_a_working_candidate(step4, cloud_run, caplog):
    # The exact match ranks first, but lacks its cloud mask. The second scene
    # is slightly less similar and has the complete inputs needed for filling.
    cloud_run.write("candidates/A0000003.img", cloud_run.mosaic)
    cloud_run.write("candidates/A0000001.img", cloud_run.mosaic - 1)
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    records = failures(caplog)
    assert len(records) == 1 and "A0000003.img" in records[0].message
    with rasterio.open(cloud_run.root / "mosaic_cloudmask.tif") as result:
        assert np.all(result.read(1)[20:30, 20:30] == 0)


def test_missing_pan_scene_is_reported(step4, cloud_run, caplog):
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    step4.main()
    records = failures(caplog)
    assert len(records) == 1
    assert "Cloud filling" in records[0].message
    assert "A0000001.img" in records[0].message and "1_cld.img" in records[0].message
    assert records[0].exc_info[0] is rasterio.errors.RasterioIOError
    assert "A0000002" in str(records[0].exc_info[1])


@pytest.mark.parametrize("pan_input", ["missing", "unreadable", "partial"])
def test_pan_preparation_failure_preserves_outputs(step4, cloud_run, pan_input):
    cloud_run.write("candidates/A0000001.img", cloud_run.mosaic - 10)
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    if pan_input == "unreadable":
        (cloud_run.root / "pan/A0000002.tif").write_text("not a raster")
    elif pan_input == "partial":
        cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0, :25, :25])

    before = {}
    for name in ("mosaic_xs.tif", "mosaic_pan.tif", "mosaic_cloudmask.tif"):
        with rasterio.open(cloud_run.root / name) as src:
            before[name] = src.read()

    step4.main()

    for name, original in before.items():
        with rasterio.open(cloud_run.root / name) as src:
            np.testing.assert_array_equal(src.read(), original, err_msg=name)
    (row,) = fill_log(cloud_run)
    assert row["filled"] == "no"
    assert row["note"].startswith("error:")


def test_valid_candidate_still_fills_without_warnings(step4, cloud_run, caplog):
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    assert not failures(caplog)
    with rasterio.open(cloud_run.root / "mosaic_cloudmask.tif") as result:
        assert np.all(result.read(1)[20:30, 20:30] == 0)


def test_nonoverlap_is_a_debug_skip(step4, cloud_run, caplog):
    cloud_run.write("candidates/A0000001.img", cloud_run.mosaic,
                    from_origin(100000, 10000, 60, 60))
    with caplog.at_level(logging.DEBUG, logger=step4.__name__):
        step4.main()
    assert not failures(caplog)
    assert any(record.levelno == logging.DEBUG and "A0000001.img" in record.message
               and "1_cld.img" in record.message for record in caplog.records)


@pytest.mark.parametrize("stage", ["scoring", "filling"])
@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
def test_stop_signals_are_not_swallowed(step4, cloud_run, monkeypatch, stage, signal):
    def stop(*args, **kwargs):
        raise signal("stop requested")

    if stage == "scoring":
        monkeypatch.setattr(step4, "structural_similarity", stop)
    else:
        monkeypatch.setattr(step4, "glob", SimpleNamespace(glob=stop))
    with pytest.raises(signal, match="stop requested"):
        step4.main()


def test_main_closes_every_dataset_it_opens(step4, cloud_run, monkeypatch):
    # Open handles stop the cldDatabase clean-up from deleting files on Windows.
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    opened = []
    real_open = rasterio.open

    def tracking_open(*args, **kwargs):
        dataset = real_open(*args, **kwargs)
        opened.append(dataset)
        return dataset

    monkeypatch.setattr(rasterio, "open", tracking_open)
    step4.main()
    assert opened
    assert [dataset.name for dataset in opened if not dataset.closed] == []


def fill_log(cloud_run):
    with open(cloud_run.root / "fill_log.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_fill_log_records_the_candidate_that_filled_each_patch(step4, cloud_run):
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    rows = fill_log(cloud_run)
    assert list(rows[0]) == step4.FILL_LOG_COLUMNS
    assert len(rows) == 1
    row = rows[0]
    assert (row["window"], row["patch"], row["candidate"], row["filled"]) == \
        ("0", "1_cld.img", "A0000001.img", "yes")
    assert 0.75 <= float(row["ssim"]) <= 1.0          # passed ssim_threshold
    assert float(row["clear_fraction"]) == 1.0
    assert int(row["pixels"]) >= 100              # the 10 x 10 cloud, dilated
    # The patch window in map coordinates (60 m grid from x=1000, y=10000)
    # covers the cloud at rows/cols 20-30.
    x_min, y_min, x_max, y_max = (float(row[c]) for c in ("x_min", "y_min", "x_max", "y_max"))
    assert x_min <= 1000 + 20 * 60 and x_max >= 1000 + 30 * 60
    assert y_max >= 10000 - 20 * 60 and y_min <= 10000 - 30 * 60
    assert (x_max - x_min) % 60 == 0 and (y_max - y_min) % 60 == 0


def test_fill_log_lists_rejected_candidates_before_the_one_used(step4, cloud_run):
    cloud_run.write("candidates/A0000003.img", cloud_run.mosaic)
    cloud_run.write("candidates/A0000001.img", cloud_run.mosaic - 1)
    cloud_run.write("masks/A0000001.tif", np.ones((64, 64), np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    rows = fill_log(cloud_run)
    assert [(r["candidate"], r["filled"]) for r in rows] == \
        [("A0000003.img", "no"), ("A0000001.img", "yes")]
    assert rows[0]["note"].startswith("error: FileNotFoundError")


def test_fill_log_explains_a_too_cloudy_candidate(step4, cloud_run):
    cloud_run.write("masks/A0000001.tif", np.full((64, 64), 20, np.uint8))
    cloud_run.write("pan/A0000002.tif", cloud_run.mosaic[0])
    step4.main()
    (row,) = fill_log(cloud_run)
    assert row["filled"] == "no" and float(row["clear_fraction"]) == 0.0
    assert "cloud_tolerance" in row["note"]


def test_fill_log_marks_patches_without_a_good_candidate(step4, cloud_run):
    noise = np.random.default_rng(3).integers(1, 255, (4, 64, 64), dtype=np.uint8)
    cloud_run.write("candidates/A0000001.img", noise)
    step4.main()
    (row,) = fill_log(cloud_run)
    assert row["candidate"] == "" and row["filled"] == "no"
    assert "ssim_threshold" in row["note"]
    assert float(row["x_min"]) < float(row["x_max"]) and float(row["y_min"]) < float(row["y_max"])
