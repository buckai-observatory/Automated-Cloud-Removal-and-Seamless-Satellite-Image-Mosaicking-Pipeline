"""Sentinel-2 demo script: --skip-download without data, output order (#46)."""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "sentinel2_demo" / "run_demo.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("run_demo", DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skip_download_without_data_gives_a_clear_message(demo, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_demo.py", "--skip-download", "--workdir", str(tmp_path)])
    monkeypatch.setattr(demo, "set_up_steps", lambda *a: pytest.fail("set_up_steps was called"))
    with pytest.raises(SystemExit) as exc:
        demo.main()
    message = str(exc.value.code)
    assert message.startswith("--skip-download: no downloaded data in")
    assert str(tmp_path / "data") in message
    assert "Rerun without --skip-download" in message


def test_missing_data_is_empty_after_a_download(demo, tmp_path):
    data = tmp_path / "data"
    for folder, scenes in (("scenes", demo.PRIMARY), ("candidates", demo.CANDIDATES)):
        (data / folder).mkdir(parents=True)
        for name, _, _ in scenes:
            (data / folder / f"{name}.img").touch()
    assert demo.missing_data(data) == [data / "land_sea_mask.tif"]
    (data / "land_sea_mask.tif").touch()
    assert demo.missing_data(data) == []


def test_step_header_comes_before_step_output_in_a_log(tmp_path):
    step = tmp_path / "step.py"
    step.write_text("print('step output')\n")
    code = ("import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location('run_demo', {str(DEMO)!r}); "
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            f"m.run_step({str(step)!r}, {str(tmp_path)!r})")
    # stdout is a pipe, as when the demo runs in CI or with its output sent to a file.
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.index("=== Running") < out.index("step output")
