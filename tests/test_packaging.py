"""The pipeline installs as a package with console commands for Steps 2-4 (#7)."""
import importlib.metadata
import os
import pathlib
import shutil
import subprocess
import sys
import sysconfig

import pytest

try:
    import tomllib
except ImportError:  # Python 3.10
    tomllib = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_mosaic import cli  # noqa: E402

COMMANDS = {"mosaic-step2": "step2", "mosaic-step3": "step3", "mosaic-step4": "step4"}


needs_tomllib = pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")


@needs_tomllib
def test_pyproject_declares_console_commands_and_step_folders():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = config["project"]["scripts"]
    assert scripts == {name: f"cloud_mosaic.cli:{step}" for name, step in COMMANDS.items()}
    package_dir = config["tool"]["setuptools"]["package-dir"]
    for step in ("step2", "step3", "step4"):
        module_name = cli.STEPS[step][1]
        folder = ROOT / package_dir[module_name.rsplit(".", 1)[0]]
        assert (folder / (module_name.rsplit(".", 1)[1] + ".py")).is_file()
        assert (folder / "run.bat").is_file()  # run.bat stays next to the script


@needs_tomllib
def test_dependencies_come_from_requirements_with_opencv_pin():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == ["requirements.txt"]
    assert "opencv-python>=4.5,<4.11" in (ROOT / "requirements.txt").read_text()


@pytest.mark.parametrize("step", ["step2", "step3", "step4"])
def test_help_exits_cleanly(step, capsys):
    with pytest.raises(SystemExit) as exc:
        getattr(cli, step)(["--help"])
    assert exc.value.code == 0
    assert cli.STEPS[step][2] in capsys.readouterr().out


@pytest.mark.parametrize("step", ["step2", "step3", "step4"])
def test_command_runs_main_inside_the_working_folder(step, tmp_path, monkeypatch):
    para_file = cli.STEPS[step][2]
    (tmp_path / para_file).write_text("{}")
    seen = []

    class FakeStep:
        @staticmethod
        def main():
            seen.append(pathlib.Path.cwd())

    monkeypatch.setattr(cli, "_load_step", lambda name: FakeStep)
    start = pathlib.Path.cwd()
    assert getattr(cli, step)([str(tmp_path)]) == 0
    assert seen == [tmp_path.resolve()]
    assert pathlib.Path.cwd() == start


def test_missing_parameter_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load_step", lambda name: pytest.fail("step was loaded"))
    with pytest.raises(SystemExit) as exc:
        cli.step4([str(tmp_path)])
    assert exc.value.code == 2


# Run in a fresh interpreter started outside the repository, so that neither the
# source folder cloud_mosaic/ nor a leftover cloud_removal_mosaicking.egg-info
# from `pip install .` (both found through the repository root on sys.path)
# is taken for an installed package (#50).
_FIND_STEPS = ("import importlib.util, sys; "
               "sys.exit(importlib.util.find_spec('cloud_mosaic.step2') is None)")


def _installed(flags=(), env=None):
    """True if the installed package, with its step subpackages, can be imported."""
    result = subprocess.run([sys.executable, *flags, "-c", _FIND_STEPS], capture_output=True,
                            cwd=pathlib.Path(sys.executable).parent, env=env)
    return result.returncode == 0


def test_leftover_egg_info_is_not_taken_for_an_install(tmp_path):
    # A clone after `pip install .`: the source package and the egg-info folder,
    # seen by an interpreter where the package is not installed (-S: no site-packages).
    (tmp_path / "cloud_mosaic").mkdir()
    (tmp_path / "cloud_mosaic" / "__init__.py").write_text("")
    egg_info = tmp_path / "cloud_removal_mosaicking.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: cloud-removal-mosaicking\nVersion: 0.0.0\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    by_metadata = ("import importlib.metadata as m; "
                   "print(m.distribution('cloud-removal-mosaicking').version)")
    result = subprocess.run([sys.executable, "-S", "-c", by_metadata], capture_output=True,
                            text=True, env=env, cwd=tmp_path, check=True)
    assert result.stdout.strip() == "0.0.0"  # metadata alone is fooled by the egg-info
    assert not _installed(["-S"], env)


@pytest.mark.skipif(not _installed(), reason="package not installed (pip install .)")
@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_installed_command_shows_help(command):
    scripts = sysconfig.get_path("scripts")  # bin on Linux and macOS, Scripts on Windows
    exe = shutil.which(command, path=scripts)
    assert exe is not None, f"{command} not installed in {scripts}"
    result = subprocess.run([exe, "--help"], capture_output=True, text=True, check=True)
    assert result.stdout.startswith(f"usage: {command}")


@pytest.mark.skipif(not _installed(), reason="package not installed (pip install .)")
def test_installed_package_contains_the_step_modules():
    code = ("import cloud_mosaic.step2.step2mosaic, cloud_mosaic.step3.mosaicPan_block_rs, "
            "cloud_mosaic.step4.step4cloud_removal")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=pathlib.Path(sys.executable).parent)
