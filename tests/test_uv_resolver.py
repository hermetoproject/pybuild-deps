"""Tests for the uv-based dependency resolver."""

import pytest

from pybuild_deps.compile_build_dependencies import (
    ResolvedDependency,
    resolve_with_uv,
)
from pybuild_deps.exceptions import UnsolvableDependenciesError


def test_resolved_dependency_is_frozen():
    """ResolvedDependency is immutable."""
    dep = ResolvedDependency(name="foo", version="1.0")
    with pytest.raises(AttributeError):
        dep.name = "bar"


@pytest.mark.e2e
def test_resolve_simple_deps():
    """Resolve a simple dependency list with uv."""
    results = resolve_with_uv(["setuptools>=42", "wheel"], package="test")
    names = {r.name for r in results}
    assert "setuptools" in names
    assert "wheel" in names
    for dep in results:
        assert dep.version


@pytest.mark.e2e
def test_resolve_with_constraints():
    """Constraints pin resolution to specific versions."""
    results = resolve_with_uv(
        ["setuptools>=42"],
        constraints=["setuptools==75.8.2"],
        package="test",
    )
    setuptools = next(r for r in results if r.name == "setuptools")
    assert setuptools.version == "75.8.2"


@pytest.mark.e2e
def test_resolve_with_hashes():
    """--generate-hashes produces hash data."""
    results = resolve_with_uv(["wheel"], generate_hashes=True, package="test")
    wheel = next(r for r in results if r.name == "wheel")
    assert wheel.hashes
    assert any(h.startswith("sha256:") for h in wheel.hashes)


@pytest.mark.e2e
def test_resolve_conflicting_deps():
    """Conflicting deps raise UnsolvableDependenciesError."""
    with pytest.raises(UnsolvableDependenciesError):
        resolve_with_uv(["setuptools>=70", "setuptools<60"], package="test")
