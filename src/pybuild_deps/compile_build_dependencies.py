"""
compile build dependencies module.

Heavily rely on pip-tools BacktrackingResolver and our own find_build_deps
to recursively find all build dependencies and generate a pinned list
of build dependencies.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pip._internal.exceptions import DistributionNotFound
from pip._internal.req import InstallRequirement
from pip._internal.req.constructors import install_req_from_req_string
from pip._vendor.resolvelib.resolvers import ResolutionImpossible
from piptools.repositories import PyPIRepository
from piptools.resolver import BacktrackingResolver
from piptools.utils import key_from_ireq


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .exceptions import PyBuildDepsError, UnsolvableDependenciesError
from .finder import find_build_dependencies
from .logger import log
from .utils import get_version


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
    """Resolve exact build dependencies."""

    def __init__(self, repository: PyPIRepository) -> None:
        self.repository = repository
        self.resolver = None

    def resolve(
        self,
        install_requirements: Iterable[InstallRequirement],
        existing_constraints: dict[str, InstallRequirement] | None = None,
        dependency_cache: dict[str, InstallRequirement] | None = None,
    ) -> set[InstallRequirement]:
        """Resolve all build dependencies for a given set of dependencies."""
        all_build_deps = []

        # reuse or initialize constraints (following what piptools expects downstream)
        # and our dependency cache
        existing_constraints = existing_constraints or {
            key_from_ireq(ireq): ireq for ireq in install_requirements
        }
        dependency_cache = dependency_cache or {}

        for ireq in install_requirements:
            log.info("=" * 80)
            log.info(str(ireq))
            log.info("-" * 80)
            req_str = str(ireq.req)
            if req_str in dependency_cache:
                all_build_deps.extend(dependency_cache[req_str])
                log.debug(f"{ireq.req} was already solved, moving on...")
                continue
            # resolve ireq's build dependencies
            build_dependencies = self._resolve_build_deps_for_ireq(
                ireq, existing_constraints
            )
            if not build_dependencies:
                dependency_cache[req_str] = set()
                continue
            # dependencies of build dependencies might have their own build
            # dependencies, so let's recursively search for those.
            build_deps_qty = 0
            while len(build_dependencies) != build_deps_qty:
                build_deps_qty = len(build_dependencies)
                build_dependencies |= self.resolve(
                    build_dependencies,
                    existing_constraints=existing_constraints,
                    dependency_cache=dependency_cache,
                )
                build_dependencies = deduplicate_install_requirements(
                    build_dependencies
                )

            dependency_cache[req_str] = build_dependencies

            all_build_deps.extend(build_dependencies)

        return deduplicate_install_requirements(all_build_deps)

    def _resolve_build_deps_for_ireq(
        self,
        ireq: InstallRequirement,
        constraints: dict[str, InstallRequirement],
    ) -> set[InstallRequirement]:
        # find build dependencies for ireq
        build_ireqs = set(self._find_build_dependencies(ireq))
        if not build_ireqs:
            return set()
        # build_ireqs isn't a comprehensive list of dependencies yet.
        # They represent exclusively the build requirements which are most
        # likely not even pinned yet. For instance, consider a package with the
        # following section on pyproject.toml:
        #
        # [build-system]
        # requires = ["poetry-core>=1.0.0"]
        #
        # For ireq representing the package above, build_ireqs would be equivalent to
        # {"poetry-core>=1.0.0"}. We don't want that. We want a set of pinned
        # dependencies and all it's runtime dependencies as well.
        #
        # Now we need to resolve a version for the build dependencies and also find
        # which packages they depend on. Following the example above, we would need to
        # find what is required to install poetry-core and resolve a version of it.
        try:
            # Attempt to resolve ireq's transitive dependencies using
            # runtime requirements as constraint. This is same concept of
            # "constraint" that can be used with pip, like when running
            # "pip install -c constraints.txt some-package"
            return self._resolve_with_piptools(
                package=str(ireq.req),
                ireqs=build_ireqs,
                constraints=constraints,
            )
        except UnsolvableDependenciesError:
            # Being unsolvable on the previous step doesn't mean a transitive
            # dependency is actually unsolvable. Per PEP-517, transitive
            # dependencies are built in isolated environments. We only
            # try building with constraints to avoid ending up with an unnecessarily
            # large list of dependencies to manage.

            # If this step fails, the same exception will bubble up and explode
            # in an error.
            return self._resolve_with_piptools(
                package=str(ireq.req),
                ireqs=build_ireqs,
            )

    def _resolve_with_piptools(
        self,
        package: str,
        ireqs: Iterable[InstallRequirement],
        constraints: dict[InstallRequirement] | None = None,
    ) -> set[InstallRequirement]:
        # backup unsafe data before overriding resolver, we will need it later
        # on piptools writer to export the file
        unsafe_packages = getattr(self.resolver, "unsafe_packages", set())
        unsafe_constraints = getattr(self.resolver, "unsafe_constraints", set())
        # override resolver - we don't want references from other
        self.resolver = BacktrackingResolver(
            constraints=ireqs,
            existing_constraints=constraints or {},
            repository=self.repository,
            allow_unsafe=True,
        )
        try:
            requirements = self.resolver.resolve()
        except DistributionNotFound as err:
            if isinstance(err.__cause__, ResolutionImpossible):  # pragma: no branch
                raise UnsolvableDependenciesError(package, err.__cause__.args)  # noqa: B904
            # TODO: We don't know how to reproduce the condition below, or even know if
            # it is possible.
            raise  # pragma: no cover
        self.resolver.unsafe_packages |= unsafe_packages
        self.resolver.unsafe_constraints |= unsafe_constraints
        return requirements

    def _find_build_dependencies(
        self,
        ireq: InstallRequirement,
    ) -> Generator[InstallRequirement]:
        """Find build dependencies for a given ireq."""
        ireq_version = get_version(ireq)
        for build_dep in find_build_dependencies(
            ireq.name,
            ireq_version,
            raise_setuppy_parsing_exc=False,
        ):
            # The original 'find_build_dependencies' function is very naive by design.
            # It only returns a simple list of strings representing builds dependencies.
            # In order to feed those to piptools resolver, those strings need to be
            # converted to InstallRequirements.
            yield install_req_from_req_string(build_dep, comes_from=ireq.name)


def deduplicate_install_requirements(_ireqs: Iterable[InstallRequirement]):
    """Deduplicate InstallRequirements."""
    unique_ireqs = {}
    for ireq in _ireqs:
        req_tuple = ireq.name, get_version(ireq)
        if req_tuple not in unique_ireqs:
            # NOTE: piptools hacks pip's InstallRequirement to allow support from
            # multiple sources. Let's use the same attr so piptools file writer can
            # use this information.
            # https://github.com/jazzband/pip-tools/blob/53309647980e2a4981db54c0033f98c61142de0b/piptools/resolver.py#L118-L122
            # https://github.com/jazzband/pip-tools/blob/53309647980e2a4981db54c0033f98c61142de0b/piptools/writer.py#L309-L314
            ireq._source_ireqs = set(getattr(ireq, "_source_ireqs", {ireq}))
            unique_ireqs[req_tuple] = ireq
        else:
            _ireqs = set(getattr(ireq, "_source_ireqs", {ireq}))
            unique_ireqs[req_tuple]._source_ireqs |= _ireqs
    return set(unique_ireqs.values())
