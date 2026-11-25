"""Step 3 names a missing Step 2 output instead of raising a traceback (#94)."""

import json

import numpy as np
import pytest


def test_missing_process_order_exits_with_one_line(step3, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "para_pan.txt").write_text(json.dumps({
        "res": 2, "trueBits": 12, "StartLetter": "a", "upscale_factor": 4,
    }), encoding="utf-8")
    for name in ("transform.npy", "allWindow.npy", "ImgInd.npy", "Union_gt.npy"):
        np.save(name, [])

    with pytest.raises(SystemExit) as exit_info:
        step3.main()

    message = str(exit_info.value.code)
    assert "\n" not in message
    assert "missing ProcessOrder.txt" in message
    assert "Step 2" in message


def test_all_step2_files_present_passes(step3, tmp_path):
    (tmp_path / "ProcessOrder.txt").write_text("a0000001.img", encoding="utf-8")
    for name in ("transform.npy", "allWindow.npy", "ImgInd.npy", "Union_gt.npy"):
        np.save(tmp_path / name, [])
    step3.check_step2_files(str(tmp_path))
