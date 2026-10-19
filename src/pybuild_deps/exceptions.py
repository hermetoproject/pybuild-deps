"""custom exceptions for pybuild-deps."""

from __future__ import annotations


class PyBuildDepsError(Exception):
    """Custom exception for pybuild-deps."""


class NoSDistError(PyBuildDepsError):
    """Package doesn't distribute an sdist."""


class UnsolvableDependenciesError(PyBuildDepsError):
    """Unsolvable dependencies."""

    def __init__(self, package: str, details: str):
        self.package = package
        self.details = details

    def __str__(self):
        return (
            f"Failed to resolve dependencies for package "
            f"'{self.package}':\n{self.details}"
        )
