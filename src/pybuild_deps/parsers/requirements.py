"""parser for requirement.txt files."""

from __future__ import annotations

import os
import re
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from packaging.requirements import InvalidRequirement, Requirement

from pybuild_deps.exceptions import PyBuildDepsError


# A "#" begins a comment only at line start or after whitespace, so URL
# fragments like "...#egg=name" are preserved. Mirrors pip's own rule.
_LINE_COMMENT = re.compile(r"(^|\s)#.*$")
# pip only expands the ${NAME} form, with an upper case POSIX name.
_ENV_VAR = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)\}")
# -r/-c and their long forms, with the path attached, spaced or after "=".
_INCLUDE = re.compile(
    r"^(?:-(?P<short>[rc])\s*|--(?P<long>requirement|constraint)(?:=|\s+))"
    r"(?P<path>\S.*)$"
)


@dataclass
class RequirementsFile:
    """Contents of a requirements file and everything it includes.

    ``requirements`` are the packages whose build dependencies are wanted.
    ``constraints`` come from ``-c`` files: pins that only steer versions.
    ``options`` are global pip option lines such as ``--index-url``.
    """

    requirements: list[Requirement] = field(default_factory=list)
    constraints: list[Requirement] = field(default_factory=list)
    options: list[str] = field(default_factory=list)


def read_requirements_file(filename: str) -> RequirementsFile:
    """Read a requirements file, following -r and -c includes.

    Validates all requirements before filtering inactive environment markers.
    Unlike pip/pip-compile, this catches invalid pinning on all platforms.
    """
    result = RequirementsFile()
    _read(Path(filename), constraint=False, result=result)
    return result


def parse_requirements(filename: str) -> Generator[Requirement]:
    """Parse pinned requirements from a requirements.txt file."""
    yield from read_requirements_file(filename).requirements


def _read(
    path: Path,
    constraint: bool,
    result: RequirementsFile,
    active_files: set[Path] | None = None,
) -> None:
    if active_files is None:
        active_files = set()
    path = path.resolve()
    if path in active_files:
        raise PyBuildDepsError(f"requirements file include cycle at '{path}'.")
    active_files.add(path)
    try:
        for line in _logical_lines(path):
            _read_line(line, path, constraint, result, active_files)
    finally:
        active_files.remove(path)


def _read_line(
    line: str,
    path: Path,
    constraint: bool,
    result: RequirementsFile,
    active_files: set[Path],
) -> None:
    include = _INCLUDE.match(line)
    if include:
        nested = Path(include["path"])
        if not nested.is_absolute():
            nested = path.parent / nested
        nested_is_constraint = (include["short"] or include["long"]).startswith("c")
        _read(nested, constraint or nested_is_constraint, result, active_files)
    elif line.startswith(("-e", "--editable")):
        raise PyBuildDepsError(
            f"editable requirement '{line}' is not supported "
            "(pybuild-deps only supports pinned dependencies)."
        )
    elif line.startswith("-"):
        if line not in result.options:
            result.options.append(line)
    else:
        req = _parse_requirement(line)
        if not constraint and not _is_pinned(req):
            raise PyBuildDepsError(
                f"requirement '{req}' is not exact "
                "(pybuild-deps only supports pinned dependencies)."
            )
        if req.marker and not req.marker.evaluate():
            return
        target = result.constraints if constraint else result.requirements
        target.append(req)


def _logical_lines(path: Path) -> Iterable[str]:
    """Yield lines with continuations joined, comments stripped, ${VARS} set."""
    try:
        text = path.read_text()
    except OSError as err:
        raise PyBuildDepsError(f"Could not read requirements file '{path}'.") from err
    continued = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.endswith("\\"):
            continued += line[:-1].strip() + " "
            continue
        line = continued + line
        continued = ""
        yield from _clean(line)
    yield from _clean(continued)


def _clean(line: str) -> Iterable[str]:
    line = _LINE_COMMENT.sub("", line).strip()
    if line:
        yield _ENV_VAR.sub(lambda m: os.environ.get(m["name"]) or m[0], line)


def _parse_requirement(line: str) -> Requirement:
    """Parse the requirement, ignoring per-requirement options like --hash.

    Like pip, the requirement ends at the first token starting with "-".
    """
    tokens = line.split()
    end = next((i for i, t in enumerate(tokens) if t.startswith("-")), len(tokens))
    requirement = " ".join(tokens[:end]).strip()
    try:
        return Requirement(requirement)
    except InvalidRequirement as err:
        raise PyBuildDepsError(
            f"Failed to parse requirement '{requirement}': {err}"
        ) from err


_VCS_PREFIXES = ("git+", "hg+", "svn+", "bzr+")


def _is_pinned(req: Requirement) -> bool:
    """Check if requirement is pinned (==), a VCS link with ref, or a direct URL."""
    if req.url:
        parsed = urlparse(req.url)
        if any(parsed.scheme.startswith(p) for p in _VCS_PREFIXES):
            return "@" in parsed.path
        return True
    specs = list(req.specifier)
    return len(specs) == 1 and specs[0].operator in ("==", "===")
