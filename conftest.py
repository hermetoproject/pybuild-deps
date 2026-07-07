"""pytest configuration."""

from importlib import reload

import pytest

from pybuild_deps import finder


@pytest.fixture(autouse=True)
def cache(mocker, tmp_path):
    """Mock pybuild-deps cache."""
    mocked_cache = tmp_path / "cache"
    mocker.patch("pybuild_deps.constants.CACHE_PATH", mocked_cache)
    mocker.patch("pybuild_deps.cache.CACHE_PATH", mocked_cache)
    mocker.patch("pybuild_deps.source.CACHE_PATH", mocked_cache)
    # reload finder module to force applying the patched decorator
    reload(finder)

    yield mocked_cache
