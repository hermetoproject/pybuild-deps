"""test compile_build_dependencies module."""

import logging

import pytest

from pybuild_deps import compile_build_dependencies
from pybuild_deps.compile_build_dependencies import (
    BuildDependencyCompiler,
    ResolvedDependency,
)
from pybuild_deps.exceptions import UnsolvableDependenciesError


@pytest.fixture
def compiler() -> BuildDependencyCompiler:
    """BuildDependencyCompiler instance."""
    return BuildDependencyCompiler()


@pytest.fixture
def build_deps(mocker):
    """Map of package name to the build requirements find_build_dependencies gives."""
    mapping: dict[str, list[str]] = {}
    mocker.patch.object(
        compile_build_dependencies,
        "find_build_dependencies",
        side_effect=lambda name, version, **kwargs: mapping.get(name, []),
    )
    return mapping


def test_resolve_recursively(compiler, build_deps, local_index):
    """Build dependencies of build dependencies are resolved too."""
    build_deps.update({"app": ["backend"], "backend": ["plugin<2"]})
    results = compiler.resolve(["app==1.0"], options=local_index)
    assert sorted(results, key=lambda d: d.name) == [
        ResolvedDependency(name="backend", version="1.0", via=frozenset({"app"})),
        ResolvedDependency(name="helper", version="3.0", via=frozenset({"backend"})),
        ResolvedDependency(name="plugin", version="1.0", via=frozenset({"backend"})),
    ]


def test_resolve_merges_annotations(compiler, build_deps, local_index):
    """A dependency needed by several packages is listed once, via all of them."""
    build_deps.update({"app": ["backend"], "other": ["helper>=2"]})
    results = compiler.resolve(["app==1.0", "other==1.0"], options=local_index)
    assert [dep.name for dep in results].count("helper") == 1
    assert {dep.name: dep for dep in results}["helper"] == ResolvedDependency(
        name="helper", version="3.0", via=frozenset({"backend", "other"})
    )


def test_resolve_with_pins(compiler, build_deps, local_index):
    """Compatible runtime pins are kept, a conflicting one is dropped."""
    build_deps["app"] = ["backend", "plugin"]
    results = compiler.resolve(
        ["app==1.0"],
        pins=["helper==1.0", "plugin==1.0"],
        options=local_index,
    )
    versions = {dep.name: dep.version for dep in results}
    assert versions == {"backend": "1.0", "helper": "3.0", "plugin": "1.0"}


def test_resolve_relaxes_conflicting_transitive_constraint(
    compiler, build_deps, local_index
):
    """A conflicting transitive constraint becomes a preference after retry."""
    build_deps["app"] = ["backend"]
    results = compiler.resolve(["app==1.0"], pins=["helper<2"], options=local_index)
    versions = {dep.name: dep.version for dep in results}
    assert versions == {"backend": "1.0", "helper": "3.0"}


def test_resolve_pins_hold(compiler, build_deps, local_index):
    """A runtime pin holds even when it means an older build dependency."""
    build_deps["app"] = ["tool"]
    results = compiler.resolve(["app==1.0"], pins=["helper==2.0"], options=local_index)
    versions = {dep.name: dep.version for dep in results}
    assert versions == {"helper": "2.0", "tool": "1.0"}


def test_unsolvable_dependencies(compiler, build_deps, local_index, mocker):
    """Unsolvable build requirements fail at once instead of being retried."""
    build_deps["app"] = ["helper>=3", "helper<2"]
    resolve_with_uv = mocker.spy(compile_build_dependencies, "resolve_with_uv")
    with pytest.raises(UnsolvableDependenciesError):
        compiler.resolve(["app==1.0"], pins=["helper==1.0"], options=local_index)
    assert resolve_with_uv.call_count == 1


def test_empty_dependencies(compiler):
    """Test handling empty dependency list."""
    results = compiler.resolve([])
    assert results == []


@pytest.mark.e2e
def test_compile_greenpath(compiler):
    """Test compiling build dependencies happy path."""
    results = compiler.resolve(["cryptography==40.0.0"])
    via = {dep.name: dep.via for dep in results}
    assert "cryptography" in via["setuptools-rust"]
    assert "setuptools-rust" in via["setuptools-scm"]


@pytest.mark.e2e
def test_dependency_with_complex_setup_py(compiler, caplog):
    """Ensure unparseable setup.py won't get in the way."""
    caplog.set_level(logging.ERROR)
    compiler.resolve(["grpcio==1.59.0"])
    assert caplog.messages[-1] == "Unable to parse setup.py for package grpcio==1.59.0."
