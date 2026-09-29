"""
compile build dependencies module.

Heavily rely on pip-tools BacktrackingResolver and our own find_build_deps
to recursively find all build dependencies and generate a pinned list
of build dependencies.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections.abc import Generator, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from pip._internal.exceptions import DistributionNotFound
from pip._internal.req import InstallRequirement
from pip._internal.req.constructors import install_req_from_req_string
from pip._vendor.resolvelib.resolvers import ResolutionImpossible
from piptools.repositories import PyPIRepository
from piptools.resolver import BacktrackingResolver
from piptools.utils import key_from_ireq
from uv import find_uv_bin

from .exceptions import PyBuildDepsError, UnsolvableDependenciesError
from .finder import find_build_dependencies
from .logger import log
from .utils import get_version


@dataclass(frozen=True)
class ResolvedDependency:
    """A resolved package with name, version, hashes and what requires it."""

    name: str
    version: str
    hashes: tuple[str, ...] = ()
    via: frozenset[str] = frozenset()


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
            name, _, version = tokens[0].partition("==")
            hashes = tuple(
                t[len("--hash=") :] for t in tokens[1:] if t.startswith("--hash=")
            )
            results.append(
                ResolvedDependency(name=name, version=version, hashes=hashes)
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
        version = next(iter(req.specifier)).version
        if all(
            specifier.contains(version, prereleases=True)
            for specifier in specifiers.get(canonicalize_name(req.name), [])
        ):
            compatible.append(pin)
    return compatible


def _run_uv(
    deps: list[str],
    package: str,
    options: list[str],
    generate_hashes: bool,
    constraints: Sequence[str] = (),
    preferences: Sequence[str] = (),
) -> list[ResolvedDependency]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        Path(tmp_dir, _INPUT_FILE).write_text("\n".join([*options, *deps]) + "\n")
        if preferences:
            # uv prefers the versions already in its output file
            Path(tmp_dir, _OUTPUT_FILE).write_text("\n".join(preferences) + "\n")

        try:
            cmd = [
                find_uv_bin(),
                "pip",
                "compile",
                "--no-config",
                "--python",
                sys.executable,
                "--annotation-style",
                "line",
                "-o",
                _OUTPUT_FILE,
                _INPUT_FILE,
            ]
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
