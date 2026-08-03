"""test compile_build_dependencies module."""

import logging

import pytest

from pybuild_deps.compile_build_dependencies import BuildDependencyCompiler
from pybuild_deps.exceptions import UnsolvableDependenciesError


@pytest.fixture
def compiler() -> BuildDependencyCompiler:
    """BuildDependencyCompiler instance."""
    return BuildDependencyCompiler()


@pytest.mark.e2e
def test_compile_greenpath(compiler):
    """Test compiling build dependencies happy path."""
    results = compiler.resolve(["cryptography==40.0.0"])
    names = {dep.name for dep in results}
    assert {"setuptools-rust", "setuptools-scm"}.issubset(names)


@pytest.mark.e2e
def test_dependency_with_complex_setup_py(compiler, caplog):
    """Ensure unparseable setup.py won't get in the way."""
    caplog.set_level(logging.ERROR)
    compiler.resolve(["grpcio==1.59.0"])
    assert caplog.messages[-1] == "Unable to parse setup.py for package grpcio==1.59.0."


def test_empty_dependencies(compiler):
    """Test handling empty dependency list."""
    results = compiler.resolve([])
    assert results == []


@pytest.mark.e2e
def test_unsolvable_dependencies(compiler):
    """Test trying to solve impossible dependency combinations."""
    with pytest.raises(UnsolvableDependenciesError):
        compiler._resolve_build_deps(
            "foo==1.2.3",
            ["setuptools<42", "setuptools>=42"],
            constraints=None,
            generate_hashes=False,
        )
