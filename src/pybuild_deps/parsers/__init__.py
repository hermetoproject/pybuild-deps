"""Parsers for PyBuild Deps."""

from configparser import ConfigParser


try:
    import tomllib as toml
# no cover is needed to deal with demand for 100% coverage
except ImportError:  # pragma: no cover
    import tomli as toml  # pragma: no cover
import re

from .requirements import parse_requirements
from .setup_py import (
    SetupPyParsingError,
    parse_setup_py,
)


def parse_pyproject_toml(content):
    """Parse build requirements from pyproject.toml files."""
    try:
        return toml.loads(content)["build-system"]["requires"]
    except KeyError:
        return []


def parse_setup_cfg(content):
    """Parse build requirements from setup.cfg files."""
    config = ConfigParser()
    config.read_string(content)
    try:
        build_requirements = config["options"]["setup_requires"]
    except KeyError:
        return []

    return [
        r.strip()
        for req in build_requirements.strip().splitlines()
        for r in re.split(";|,", req.strip())
    ]
