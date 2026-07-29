"""Test source module."""

import zipfile
from pathlib import Path

import pytest

from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.source import (
    _download_archive,
    _extract_archive,
    _unwrap_root_dir,
    _validate_archive_members,
    get_package_source,
)


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


def test_unwrap_root_dir_strips_single_subdir(tmp_path):
    """Single subdirectory gets unwrapped."""
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    subdir = extract_dir / "package-1.0"
    subdir.mkdir()
    (subdir / "setup.py").write_text("setup()")
    (subdir / "README").write_text("hello")

    _unwrap_root_dir(extract_dir, tmp_path)

    assert (tmp_path / "setup.py").exists()
    assert (tmp_path / "README").exists()
    assert not extract_dir.exists()


def test_unwrap_root_dir_preserves_multiple_children(tmp_path):
    """Multiple children stay at the same level."""
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    (extract_dir / "file_a").write_text("a")
    (extract_dir / "file_b").write_text("b")

    _unwrap_root_dir(extract_dir, tmp_path)

    assert (tmp_path / "file_a").exists()
    assert (tmp_path / "file_b").exists()
    assert not extract_dir.exists()


def test_safe_archive_members_accepted():
    """Safe archive members pass validation."""
    _validate_archive_members(["pkg-1.0/setup.py", "pkg-1.0/README"], "https://x")


@pytest.mark.parametrize(
    "member",
    [
        pytest.param("../etc/passwd", id="path_traversal"),
        pytest.param("/etc/passwd", id="absolute_path"),
        pytest.param("pkg/../../../etc/shadow", id="nested_traversal"),
        pytest.param("..\\etc\\passwd", id="windows_path_traversal"),
    ],
)
def test_unsafe_archive_members_rejected(member):
    """Unsafe archive members raise PyBuildDepsError."""
    with pytest.raises(PyBuildDepsError):
        _validate_archive_members([member], "https://x")


def test_download_archive_success(tmp_path, mocker):
    """Downloaded content is written to .pybuild_archive."""
    mock_response = mocker.Mock()
    mock_response.iter_content.return_value = [b"fake archive content"]
    mock_response.raise_for_status = mocker.Mock()
    mocker.patch("pybuild_deps.source.requests.Session.get", return_value=mock_response)

    dest = tmp_path / "output"
    dest.mkdir()
    _download_archive("https://example.com/pkg.tar.gz", "test-pkg", dest)

    assert (dest / ".pybuild_archive").exists()
    assert (dest / ".pybuild_archive").read_bytes() == b"fake archive content"


def test_zip_extraction(tmp_path):
    """Zip archives are extracted with per-file safety checks."""
    dest = tmp_path / "output"
    dest.mkdir()
    archive = dest / ".pybuild_archive"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pkg-1.0/setup.py", "setup()")
        zf.writestr("pkg-1.0/README", "hello")

    _extract_archive(dest, "https://example.com/pkg.zip", "test-pkg")

    assert (dest / "setup.py").exists()
    assert (dest / "README").exists()
