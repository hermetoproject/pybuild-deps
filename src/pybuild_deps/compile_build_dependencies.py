"""compile build dependencies module.

Recursively find all build dependencies and resolve them to pinned
versions using uv pip compile.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import partial
from itertools import takewhile
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, urlparse

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from uv import find_uv_bin

from .exceptions import PyBuildDepsError, UnsolvableDependenciesError
from .finder import find_build_dependencies
from .logger import log


@dataclass(frozen=True)
class ResolvedDependency:
    """A resolved package with name, version, hashes and what requires it."""

    name: str
    version: str
    hashes: tuple[str, ...] = ()
    via: frozenset[str] = frozenset()
    marker: str | None = None
    url: str | None = None


_INPUT_FILE = "requirements.in"
_OUTPUT_FILE = "requirements.txt"
_CONSTRAINTS_FILE = "constraints.txt"
_PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _parse_compiled_output(text: str, package: str) -> list[ResolvedDependency]:
    """Parse ``uv pip compile`` requirements output into ResolvedDependency.

    Each pinned requirement is a ``name==version`` line, optionally followed
    by ``--hash=`` continuation lines joined with a trailing backslash. The
    line style ``# via`` annotation, inline or on the line after the hashes,
    is kept. uv's reference to its input file becomes the name of
    ``package``, whose build requires the dependency, and its reference to
    the constraints file is left out. Other comments are ignored.
    """
    match = _PROJECT_NAME.match(package)
    requested_by = canonicalize_name(match.group()) if match else package
    results: list[ResolvedDependency] = []
    buf = ""
    for raw in text.splitlines():
        code, _, annotation = raw.partition("# via ")
        code = code.strip()
        if code.startswith("#"):
            continue
        if code:
            buf = f"{buf} {code}" if buf else code
            if buf.endswith("\\"):
                buf = buf[:-1].strip()
                continue
            tokens = buf.split()
            buf = ""
            requirement_tokens = list(
                takewhile(lambda token: not token.startswith("--hash="), tokens)
            )
            requirement = Requirement(" ".join(requirement_tokens))
            specifier = next(iter(requirement.specifier), None)
            hashes = tuple(
                t[len("--hash=") :] for t in tokens[1:] if t.startswith("--hash=")
            )
            results.append(
                ResolvedDependency(
                    name=requirement.name,
                    version=specifier.version if specifier else "",
                    marker=str(requirement.marker) if requirement.marker else None,
                    url=requirement.url,
                    hashes=hashes,
                )
            )
        if annotation and results:
            sources = annotation.strip().split(", ")
            # constraints only narrow versions, they never require a package
            via = {
                requested_by if source.startswith("-r ") else source
                for source in sources
                if not source.startswith("-c ")
            }
            results[-1] = replace(results[-1], via=frozenset(via))
    return results


def resolve_with_uv(
    deps: list[str],
    package: str,
    pins: list[str] | None = None,
    options: list[str] | None = None,
    generate_hashes: bool = False,
) -> list[ResolvedDependency]:
    """Resolve dependencies using uv pip compile.

    Returns a list of ResolvedDependency with name, version, optional hashes
    and annotations. The requirements output format records every
    distribution hash for each pinned version (matching pip-compile), unlike
    pylock.toml which only records artifacts for the resolved environment.

    ``pins`` are ``name==version`` runtime pins that should hold where they
    can, the way pip-tools treats existing constraints. Pins conflicting with
    one of ``deps`` are dropped, the rest are passed as constraints. If uv
    finds no solution with them, they are passed again as preferences, which
    uv keeps only where they are compatible.

    ``options`` are pip option lines (``--index-url``, ``--find-links`` and so
    on) placed at the top of the input file, where uv honors them like pip.

    Resolution targets the running interpreter, and ``--no-config`` keeps a
    ``uv.toml`` or ``[tool.uv]`` in the working directory from changing the
    result.
    """
    pins = _compatible_pins(deps, pins or [])
    resolve = partial(_run_uv, deps, package, options or [], generate_hashes)
    if not pins:
        return resolve()
    try:
        return resolve(constraints=pins)
    except UnsolvableDependenciesError:
        return resolve(preferences=pins)


def _compatible_pins(deps: list[str], pins: list[str]) -> list[str]:
    """Drop pins that conflict with a direct requirement, as pip-tools does."""
    specifiers: dict[str, list[SpecifierSet]] = {}
    for dep in deps:
        try:
            req = Requirement(dep)
        except InvalidRequirement:
            continue  # uv reports it
        specifiers.setdefault(canonicalize_name(req.name), []).append(req.specifier)
    compatible = []
    for pin in pins:
        req = Requirement(pin)
        specs = list(req.specifier)
        if len(specs) != 1 or specs[0].operator not in ("==", "==="):
            compatible.append(pin)
            continue
        version = specs[0].version
        if all(
            specifier.contains(version, prereleases=True)
            for specifier in specifiers.get(canonicalize_name(req.name), [])
        ):
            compatible.append(pin)
    return compatible


def _uv_environment() -> dict[str, str]:
    """Translate pip index environment variables to uv equivalents."""
    env = dict(os.environ)
    # --no-config does not override an explicitly supplied config path.
    env.pop("UV_CONFIG_FILE", None)
    for pip_name, uv_name in {
        "PIP_INDEX_URL": "UV_INDEX_URL",
        "PIP_EXTRA_INDEX_URL": "UV_EXTRA_INDEX_URL",
    }.items():
        if pip_name in env and uv_name not in env:
            env[uv_name] = env[pip_name]
    if "UV_FIND_LINKS" in env:
        find_links = [
            _strip_quotes(value.strip()) for value in env["UV_FIND_LINKS"].split(",")
        ]
    elif "PIP_FIND_LINKS" in env:
        find_links = shlex.split(env["PIP_FIND_LINKS"], posix=os.name != "nt")
        find_links = [_strip_quotes(value) for value in find_links]
    else:
        find_links = []
    if find_links:
        cwd = Path.cwd()
        env["UV_FIND_LINKS"] = ",".join(
            _resolve_find_link(path.strip(), cwd) for path in find_links if path.strip()
        )
    return env


def _run_uv(
    deps: list[str],
    package: str,
    options: list[str],
    generate_hashes: bool,
    constraints: Sequence[str] = (),
    preferences: Sequence[str] = (),
) -> list[ResolvedDependency]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        Path(tmp_dir, _INPUT_FILE).write_text(
            "\n".join([*_normalize_options(options), *deps]) + "\n"
        )
        if preferences:
            # uv prefers the versions already in its output file
            Path(tmp_dir, _OUTPUT_FILE).write_text("\n".join(preferences) + "\n")

        try:
            env = _uv_environment()

            cmd = [
                find_uv_bin(),
                "pip",
                "compile",
                "--no-config",
                "--python",
                sys.executable,
                "--annotation-style",
                "line",
                "--no-strip-markers",
            ]
            if env.get("PIP_NO_INDEX", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                # uv has no UV_NO_INDEX environment variable.
                cmd.append("--no-index")
            cmd.extend(["-o", _OUTPUT_FILE, _INPUT_FILE])
            if constraints:
                Path(tmp_dir, _CONSTRAINTS_FILE).write_text(
                    "\n".join(constraints) + "\n"
                )
                cmd.extend(["-c", _CONSTRAINTS_FILE])
            if generate_hashes:
                cmd.append("--generate-hashes")
            result = subprocess.run(  # noqa: S603
                cmd,
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=300,
            )
        except FileNotFoundError as err:
            raise PyBuildDepsError(
                "uv executable not found. Reinstall pybuild-deps to restore it."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise PyBuildDepsError(
                f"Dependency resolution for '{package}' timed out after 300s"
            ) from err

        # uv exits with 1 when there's no solution and 2 on errors
        if result.returncode == 1:
            raise UnsolvableDependenciesError(package, result.stderr.strip())
        if result.returncode != 0:
            raise PyBuildDepsError(
                f"uv failed resolving dependencies for '{package}':\n"
                f"{result.stderr.strip()}"
            )

        output = Path(tmp_dir, _OUTPUT_FILE).read_text()
        return _parse_compiled_output(output, package)


def _normalize_options(options: Sequence[str]) -> list[str]:
    """Make relative local find-links paths independent of uv's temp cwd."""
    normalized: list[str] = []
    for option in options:
        raw_find_link = re.fullmatch(
            r"\s*(?P<name>-f|--find-links)(?:\s+|=)(?P<value>.*?)\s*", option
        )
        if raw_find_link:
            raw_value = _strip_quotes(raw_find_link["value"].strip())
            if PureWindowsPath(raw_value).is_absolute() or (
                os.name == "nt" and "\\" in raw_value
            ):
                normalized.append(
                    f"{raw_find_link['name']} "
                    f"{shlex.quote(_resolve_find_link(raw_value, Path.cwd()))}"
                )
                continue

        parts = shlex.split(option)
        if not parts:
            normalized.append(option)
            continue
        name, separator, value = parts[0].partition("=")
        if name not in ("-f", "--find-links"):
            normalized.append(option)
            continue
        if not separator:
            if len(parts) != 2:
                normalized.append(option)
                continue
            value = parts[1]
        parsed = urlparse(value)
        if parsed.scheme or Path(value).is_absolute():
            normalized.append(option)
            continue
        normalized.append(f"{name} {shlex.quote(str(Path.cwd() / value))}")
    return normalized


def _resolve_find_link(value: str, cwd: Path) -> str:
    """Resolve relative find-links paths before uv runs from a temp directory."""
    windows_path = PureWindowsPath(value)
    if windows_path.is_absolute():
        return _windows_path_to_uri(windows_path)
    if urlparse(value).scheme:
        return value
    if os.name == "nt" and "\\" in value:
        return _windows_path_to_uri(PureWindowsPath(cwd) / windows_path)
    resolved = cwd / value
    if isinstance(resolved, PureWindowsPath) and resolved.is_absolute():
        return _windows_path_to_uri(resolved)
    return str(resolved)


def _strip_quotes(value: str) -> str:
    """Remove one matching quote pair preserved by non-POSIX shlex parsing."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _windows_path_to_uri(path: PureWindowsPath) -> str:
    """Return a file URL so uv does not parse the drive as a URL scheme."""
    path_text = path.as_posix()
    if path.drive.startswith("\\\\"):
        return f"file://{quote(path_text.lstrip('/'), safe='/:')}"
    return f"file:///{quote(path_text, safe='/:')}"


class BuildDependencyCompiler:
    """Resolve exact build dependencies using uv."""

    def resolve(
        self,
        requirements: list[str],
        pins: list[str] | None = None,
        options: list[str] | None = None,
        dependency_cache: dict[str, list[ResolvedDependency]] | None = None,
        generate_hashes: bool = False,
    ) -> list[ResolvedDependency]:
        """Resolve all build dependencies for a given set of dependencies.

        ``pins`` are runtime pins that resolution keeps where they're
        compatible, to avoid an unnecessarily large list of build
        dependencies. ``options`` are pip option lines passed to every
        resolution.
        """
        all_build_deps: list[ResolvedDependency] = []
        dependency_cache = dependency_cache or {}

        for req_str in requirements:
            log.info("=" * 80)
            log.info(req_str)
            log.info("-" * 80)

            if req_str in dependency_cache:
                all_build_deps.extend(dependency_cache[req_str])
                log.debug(f"{req_str} was already solved, moving on...")
                continue

            name, version = _parse_name_version(req_str)
            build_deps = list(
                find_build_dependencies(name, version, raise_setuppy_parsing_exc=False)
            )
            if not build_deps:
                dependency_cache[req_str] = []
                continue

            # build_deps are bare build requirements like "poetry-core>=1.0.0".
            # Resolve them into pins, along with what they need to install.
            resolved = resolve_with_uv(
                build_deps,
                package=req_str,
                pins=pins,
                options=options,
                generate_hashes=generate_hashes,
            )
            if not resolved:
                dependency_cache[req_str] = []
                continue

            build_deps_count = 0
            while len(resolved) != build_deps_count:
                build_deps_count = len(resolved)
                sub_req_strs = [_to_requirement_string(dep) for dep in resolved]
                sub_deps = self.resolve(
                    sub_req_strs,
                    pins=pins,
                    options=options,
                    dependency_cache=dependency_cache,
                    generate_hashes=generate_hashes,
                )
                resolved = _deduplicate(resolved + sub_deps)

            dependency_cache[req_str] = resolved
            all_build_deps.extend(resolved)

        return _deduplicate(all_build_deps)


def _parse_name_version(req_str: str) -> tuple[str, str]:
    """Extract name and source identifier from a pinned requirement string."""
    try:
        requirement = Requirement(req_str)
    except InvalidRequirement as err:
        raise PyBuildDepsError(f"Cannot parse requirement '{req_str}'") from err
    if requirement.url:
        return requirement.name, requirement.url
    specifiers = list(requirement.specifier)
    if len(specifiers) == 1 and specifiers[0].operator in ("==", "==="):
        return requirement.name, specifiers[0].version
    raise PyBuildDepsError(f"Cannot parse name and version from '{req_str}'")


def _to_requirement_string(dep: ResolvedDependency) -> str:
    """Convert a resolved dependency back to a requirement for source lookup."""
    if dep.url:
        requirement = f"{dep.name} @ {dep.url}"
    else:
        requirement = f"{dep.name}=={dep.version}"
    if dep.marker:
        requirement += f" ; {dep.marker}"
    return requirement


def _deduplicate(deps: list[ResolvedDependency]) -> list[ResolvedDependency]:
    """Deduplicate resolved dependencies, merging sources and hashes."""
    seen: dict[tuple[str, str, str | None], ResolvedDependency] = {}
    for dep in deps:
        key = (canonicalize_name(dep.name), dep.url or dep.version, dep.marker)
        if key in seen:
            seen[key] = replace(
                seen[key],
                via=seen[key].via | dep.via,
                hashes=tuple(sorted(set(seen[key].hashes) | set(dep.hashes))),
            )
        else:
            seen[key] = dep
    return list(seen.values())
