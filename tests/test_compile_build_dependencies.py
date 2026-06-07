"""test compile_build_dependencies module."""

import logging

import pytest
from pip._internal.req.constructors import install_req_from_req_string
from piptools.repositories import PyPIRepository

from pybuild_deps.compile_build_dependencies import BuildDependencyCompiler
from pybuild_deps.constants import PIPTOOLS_CACHE_DIR
from pybuild_deps.exceptions import PyBuildDepsError, UnsolvableDependenciesError


@pytest.fixture
def compiler() -> BuildDependencyCompiler:
    """BuildDependencyCompiler instance."""
    repo = PyPIRepository([], cache_dir=PIPTOOLS_CACHE_DIR)
    return BuildDependencyCompiler(repo)


@pytest.mark.e2e
def test_compile_greenpath(compiler):
    """Test compiling build dependencies happy path."""
    ireq = install_req_from_req_string("cryptography==40.0.0")
    dependencies = compiler.resolve([ireq])
    deps_per_name = {req.name: req for req in dependencies}
    assert {"setuptools-rust", "setuptools-scm"}.issubset(deps_per_name.keys())
    assert deps_per_name["setuptools-rust"].comes_from == "cryptography"
    assert deps_per_name["setuptools-scm"].comes_from == "setuptools-rust"


def test_unpinned_dependency(compiler):
    """Ensure unpinned dependencies will raise the appropriate error."""
    ireq = install_req_from_req_string("cryptography<40")
    with pytest.raises(PyBuildDepsError):
        compiler.resolve([ireq])


@pytest.mark.e2e
def test_dependency_with_complex_setup_py(compiler, caplog):
    """Ensure unparseable setup.py won't get in the way."""
    caplog.set_level(logging.ERROR)
    ireq = install_req_from_req_string("grpcio==1.59.0")
    compiler.resolve([ireq])
    assert caplog.messages[-1] == "Unable to parse setup.py for package grpcio==1.59.0."


def test_empty_dependencies(compiler):
    """Test handling empty dependency list (e.g., all markers inactive)."""
    dependencies = compiler.resolve([])
    assert dependencies == set()
    assert compiler.resolver is None


@pytest.mark.e2e
def test_unsolvable_dependencies(compiler):
    """Test trying to solve impossible dependency combinations."""
    ireqs = map(install_req_from_req_string, ("setuptools<42", "setuptools>=42"))

    expected_error_msg = (
        "Impossible to resolve the following dependencies for package 'foo=1.2.3':"
        "\nsetuptools<42\nsetuptools>=42"
    )
    with pytest.raises(UnsolvableDependenciesError, match=expected_error_msg):
        compiler._resolve_with_piptools("foo=1.2.3", ireqs)
