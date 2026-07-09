"""parser for requirement.txt files."""

from __future__ import annotations

import optparse
from collections.abc import Generator

from pip._internal.index.package_finder import PackageFinder
from pip._internal.network.session import PipSession
from pip._internal.req import InstallRequirement
from pip._internal.req import parse_requirements as _parse_requirements
from pip._internal.req.constructors import (
    install_req_from_parsed_requirement,
)

from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.utils import is_supported_requirement


def parse_requirements(
    filename: str,
    session: PipSession = None,
    finder: PackageFinder | None = None,
    options: optparse.Values | None = None,
    constraint: bool = False,
    isolated: bool = False,
) -> Generator[InstallRequirement]:
    """Thin wrapper around pip's `parse_requirements`."""
    session = session or PipSession()
    for parsed_req in _parse_requirements(
        filename, session, finder=finder, options=options, constraint=constraint
    ):
        ireq = install_req_from_parsed_requirement(parsed_req, isolated=isolated)
        if not is_supported_requirement(ireq):
            raise PyBuildDepsError(
                f"requirement '{ireq}' is not exact "
                "(pybuild-deps only supports pinned dependencies)."
            )
        yield ireq
