"""compile build dependencies module.

Recursively find all build dependencies and resolve them to pinned
versions using uv pip compile.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .exceptions import PyBuildDepsError, UnsolvableDependenciesError
from .finder import find_build_dependencies
from .logger import log


@dataclass(frozen=True)
class ResolvedDependency:
    """A resolved package with name, version, and optional hashes."""

    name: str
    version: str
    hashes: tuple[str, ...] = ()


def _collect_hashes(pkg: dict[str, Any]) -> tuple[str, ...]:
    """Collect hashes from a pylock.toml package entry as algo:digest strings."""
    hashes = []
    for artifact_key in ("sdist", "wheels"):
        artifacts = pkg.get(artifact_key)
        if artifacts is None:
            continue
        if isinstance(artifacts, dict):
            artifacts = [artifacts]
        for artifact in artifacts:
            for algo, digest in artifact.get("hashes", {}).items():
                hashes.append(f"{algo}:{digest}")
    return tuple(hashes)


def resolve_with_uv(
    deps: list[str],
    package: str,
    constraints: list[str] | None = None,
    generate_hashes: bool = False,
) -> list[ResolvedDependency]:
    """Resolve dependencies using uv pip compile.

    Returns a list of ResolvedDependency with name, version, and
    optional hashes parsed from pylock.toml output.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        reqs_file = Path(tmp_dir) / "requirements.txt"
        reqs_file.write_text("\n".join(deps) + "\n")

        out_file = Path(tmp_dir) / "pylock.toml"

        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        cmd = [
            "uv",
            "pip",
            "compile",
            "--python-version",
            python_version,
            "--format",
            "pylock.toml",
            "-o",
            str(out_file),
            str(reqs_file),
        ]

        if generate_hashes:
            cmd.append("--generate-hashes")

        if constraints:
            constraints_file = Path(tmp_dir) / "constraints.txt"
            constraints_file.write_text("\n".join(constraints) + "\n")
            cmd.extend(["-c", str(constraints_file)])

        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except FileNotFoundError as err:
            raise PyBuildDepsError(
                "uv is not installed or not on PATH. "
                "Install it from https://docs.astral.sh/uv/"
            ) from err
        except subprocess.TimeoutExpired as err:
            raise PyBuildDepsError(
                f"Dependency resolution for '{package}' timed out after 300s"
            ) from err

        if result.returncode != 0:
            raise UnsolvableDependenciesError(package, result.stderr.strip())

        with open(out_file, "rb") as f:
            lockdata = tomllib.load(f)

    return [
        ResolvedDependency(
            name=pkg["name"],
            version=pkg["version"],
            hashes=_collect_hashes(pkg),
        )
        for pkg in lockdata.get("packages", [])
    ]


class BuildDependencyCompiler:
    """Resolve exact build dependencies using uv."""

    def resolve(
        self,
        requirements: list[str],
        existing_constraints: list[str] | None = None,
        dependency_cache: dict[str, list[ResolvedDependency]] | None = None,
        generate_hashes: bool = False,
    ) -> list[ResolvedDependency]:
        """Resolve all build dependencies for a given set of dependencies."""
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

            resolved = self._resolve_build_deps(
                req_str,
                build_deps,
                existing_constraints,
                generate_hashes,
            )
            if not resolved:
                dependency_cache[req_str] = []
                continue

            build_deps_count = 0
            while len(resolved) != build_deps_count:
                build_deps_count = len(resolved)
                sub_req_strs = [f"{dep.name}=={dep.version}" for dep in resolved]
                sub_deps = self.resolve(
                    sub_req_strs,
                    existing_constraints=existing_constraints,
                    dependency_cache=dependency_cache,
                    generate_hashes=generate_hashes,
                )
                resolved = _deduplicate(resolved + sub_deps)

            dependency_cache[req_str] = resolved
            all_build_deps.extend(resolved)

        return _deduplicate(all_build_deps)

    def _resolve_build_deps(
        self,
        package: str,
        build_deps: list[str],
        constraints: list[str] | None,
        generate_hashes: bool,
    ) -> list[ResolvedDependency]:
        try:
            return resolve_with_uv(
                build_deps,
                constraints=constraints,
                generate_hashes=generate_hashes,
                package=package,
            )
        except UnsolvableDependenciesError:
            return resolve_with_uv(
                build_deps,
                generate_hashes=generate_hashes,
                package=package,
            )


def _parse_name_version(req_str: str) -> tuple[str, str]:
    """Extract name and version from a pinned requirement string."""
    if "===" in req_str:
        name, version = req_str.split("===", 1)
        return name.strip(), version.strip()
    if "==" in req_str:
        name, version = req_str.split("==", 1)
        return name.strip(), version.strip()
    if " @ " in req_str:
        name, url = req_str.split(" @ ", 1)
        return name.strip(), url.strip()
    raise PyBuildDepsError(f"Cannot parse name and version from '{req_str}'")


def _deduplicate(deps: list[ResolvedDependency]) -> list[ResolvedDependency]:
    """Deduplicate resolved dependencies by (name, version)."""
    seen: dict[tuple[str, str], ResolvedDependency] = {}
    for dep in deps:
        key = (dep.name, dep.version)
        if key not in seen:
            seen[key] = dep
    return list(seen.values())
