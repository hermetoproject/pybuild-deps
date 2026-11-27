"""Collect declared build dependencies for resolved requirements."""

from __future__ import annotations

from collections.abc import Iterable

from pip._internal.req import InstallRequirement

from .exceptions import NoSDistError
from .finder import find_build_dependencies
from .logger import log
from .utils import get_version


def find_build_dependencies_for_requirements(
    requirements: Iterable[InstallRequirement],
) -> dict[str, list[str] | None]:
    """Find direct build declarations without resolving or inspecting them.

    Args:
        requirements: Resolved input requirements, in report order.

    Returns:
        dict[str, list[str] | None]: Build declarations keyed by input requirement.
        None indicates that the source distribution is unavailable. Repeated
        requirements are inspected once, and constraint entries are excluded.
    """
    results: dict[str, list[str] | None] = {}
    for ireq in requirements:
        if ireq.constraint:
            continue
        requirement = str(ireq.req)
        if requirement in results:
            continue
        try:
            results[requirement] = find_build_dependencies(
                ireq.name, get_version(ireq), raise_no_sdist_exc=True
            )
        except NoSDistError:
            log.warning(
                f"No source distribution found for {requirement}, "
                "skipping (build requirements may be incomplete)"
            )
            results[requirement] = None
    return results
