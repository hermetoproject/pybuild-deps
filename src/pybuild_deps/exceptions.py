"""custom exceptions for pybuild-deps."""

from __future__ import annotations

from collections.abc import Iterable

from pip._vendor.resolvelib.resolvers import RequirementInformation


class PyBuildDepsError(Exception):
    """Custom exception for pybuild-deps."""


class NoSDistError(PyBuildDepsError):
    """Package doesn't distribute an sdist."""


class UnsolvableDependenciesError(PyBuildDepsError):
    """Unsolvable dependencies."""

    def __init__(
        self,
        package: str,
        unsolvable_deps: Iterable[Iterable[RequirementInformation]],
    ):
        self.unsolvable_deps = unsolvable_deps
        self.package = package

    def __str__(self):
        unsolvable_deps = "\n".join(
            str(d.requirement) for deps in self.unsolvable_deps for d in deps
        )
        return (
            f"Impossible to resolve the following dependencies for package "
            f"'{self.package}':\n{unsolvable_deps}"
        )
