"""Console commands for Steps 2-4.

Each step reads its parameter file (para.txt, para_pan.txt or para_cld.txt)
from the current folder and writes its outputs there, exactly as
``python step*.py`` does. The commands take that working folder as an
argument instead, so they can be run from anywhere.
"""
import argparse
import importlib
import os
import pathlib

STEPS = {
    "step2": ("mosaic-step2", "cloud_mosaic.step2.step2mosaic", "para.txt",
              "Step 2: seamline mosaicking of the multispectral scenes."),
    "step3": ("mosaic-step3", "cloud_mosaic.step3.mosaicPan_block_rs", "para_pan.txt",
              "Step 3: panchromatic mosaic on the Step 2 seamlines."),
    "step4": ("mosaic-step4", "cloud_mosaic.step4.step4cloud_removal", "para_cld.txt",
              "Step 4: cloud removal with candidate scenes."),
}


def _load_step(module_name):
    return importlib.import_module(module_name)


def run(step, argv=None):
    """Parse ``argv``, change to the working folder and run the step's main()."""
    prog, module_name, para_file, description = STEPS[step]
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "workdir", nargs="?", default=".",
        help=f"prepared working folder containing {para_file} (default: current folder)")
    args = parser.parse_args(argv)

    workdir = pathlib.Path(args.workdir).resolve()
    if not (workdir / para_file).is_file():
        parser.error(f"{para_file} not found in {workdir}")

    # Load the step before changing folder, so import errors are reported first.
    module = _load_step(module_name)
    old_cwd = os.getcwd()
    os.chdir(workdir)
    try:
        module.main()
    finally:
        os.chdir(old_cwd)
    return 0


def step2(argv=None):
    return run("step2", argv)


def step3(argv=None):
    return run("step3", argv)


def step4(argv=None):
    return run("step4", argv)

