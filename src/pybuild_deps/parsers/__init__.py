"""Parsers for PyBuild Deps."""

from configparser import ConfigParser

from packaging.requirements import InvalidRequirement, Requirement


try:
    import tomllib as toml
except ImportError:
    import tomli as toml
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
    """Parse build requirements from setup.cfg files.

    Setuptools' declarative config uses the ``list-semi`` type for
    ``setup_requires``, meaning semicolons act as requirement separators.
    However, PEP 508 also uses semicolons to introduce environment
    markers (e.g. ``; python_version>="3.8"``).

    To disambiguate: each line is first validated as a complete PEP 508
    requirement string.  If valid, it is kept intact (the semicolon is a
    marker introducer).  If invalid, semicolons are treated as
    ``list-semi`` separators.
    """
    config = ConfigParser()
    config.read_string(content)
    try:
        build_requirements = config["options"]["setup_requires"]
    except KeyError:
        return []

    results = []
    for line in build_requirements.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            Requirement(line)
            results.append(line)
        except InvalidRequirement:
            results.extend(r for p in line.split(";") if (r := p.strip()))
    return results
