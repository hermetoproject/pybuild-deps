"""parser for requirement.txt files."""

from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

from packaging.requirements import InvalidRequirement, Requirement

from pybuild_deps.exceptions import PyBuildDepsError


_COMMENT_RE = re.compile(r"(^|\s+)#.*$")


def parse_requirements(filename: str) -> Generator[Requirement]:
    """Parse pinned requirements from a requirements.txt file.

    Validates all requirements before filtering inactive environment markers.
    Unlike pip/pip-compile, this catches invalid pinning on all platforms.
    """
    for line in _read_requirement_lines(filename):
        try:
            req = Requirement(line)
        except InvalidRequirement as err:
            raise PyBuildDepsError(
                f"Failed to parse requirement '{line}': {err}"
            ) from err

        if not _is_pinned(req):
            raise PyBuildDepsError(
                f"requirement '{req}' is not exact "
                "(pybuild-deps only supports pinned dependencies)."
            )
        if req.marker and not req.marker.evaluate():
            continue
        yield req


def _read_requirement_lines(filename: str) -> Generator[str]:
    """Read non-empty, non-comment lines from a requirements file.

    Handles line continuations (backslash), strips inline comments,
    and follows -r/-c includes recursively.
    """
    path = Path(filename)
    continued = ""
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line.endswith("\\"):
            continued += line[:-1].strip() + " "
            continue
        line = continued + line
        continued = ""

        line = _COMMENT_RE.sub("", line).strip()
        if not line:
            continue

        if line.startswith(("-r ", "--requirement ")):
            ref_path = line.split(None, 1)[1]
            if not Path(ref_path).is_absolute():
                ref_path = str(path.parent / ref_path)
            yield from _read_requirement_lines(ref_path)
            continue

        if line.startswith(("-c ", "--constraint ")):
            continue

        if line.startswith("-"):
            continue

        yield line

    if continued:
        yield continued.strip()


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
