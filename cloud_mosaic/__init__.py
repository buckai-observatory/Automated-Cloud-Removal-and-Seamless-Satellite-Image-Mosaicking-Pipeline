"""Automated cloud removal and seamless satellite image mosaicking pipeline."""
try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("cloud-removal-mosaicking")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0"
