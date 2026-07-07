"""Test source module."""

from pathlib import Path

import pytest

from pybuild_deps.source import get_package_source


@pytest.mark.e2e
def test_get_package_source(
    cache: Path,
):
    """End to end testing for find-build-deps command."""
    assert not cache.exists()
    source_tarball = get_package_source("cryptography", "40")
    assert cache.exists()
    assert source_tarball.is_relative_to(cache)
    assert source_tarball == cache / "cryptography" / "40" / "source.tar.gz"
    last_modified_at = source_tarball.stat().st_mtime
    # invoke it again to test the path for a cached result
    source_tarball_cached = get_package_source("cryptography", "40")
    assert source_tarball_cached.stat().st_mtime == last_modified_at
