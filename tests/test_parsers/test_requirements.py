"""test requirements parser."""

from pathlib import Path

import pytest

from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.parsers import parse_requirements


def test_pinned_requirements(tmp_path, mocker):
    """Test parsing requirements with pinned dependencies."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==40.0.0")
    requirements_list = list(parse_requirements(str(requirements_path), mocker.Mock()))
    assert [r.name for r in requirements_list] == ["cryptography"]


def test_unpinned_requirements(tmp_path, mocker):
    """Test parsing requirements with unpinned dependencies."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography>40")
    with pytest.raises(PyBuildDepsError):
        list(parse_requirements(str(requirements_path), mocker.Mock()))


def test_inactive_environment_markers(tmp_path, mocker):
    """Test that requirements with inactive environment markers are filtered."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("pywin32==311 ; sys_platform == 'impossible_platform'")
    requirements_list = list(parse_requirements(str(requirements_path), mocker.Mock()))
    assert requirements_list == []


def test_active_environment_markers(tmp_path, mocker):
    """Test that requirements with active environment markers are kept."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==40.0.0 ; python_version >= '3.0'")
    requirements_list = list(parse_requirements(str(requirements_path), mocker.Mock()))
    assert len(requirements_list) == 1
    assert requirements_list[0].name == "cryptography"


def test_mixed_markers(tmp_path, mocker):
    """Test mixed active and inactive markers."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "cryptography==40.0.0 ; python_version >= '3.0'\n"
        "pywin32==311 ; sys_platform == 'impossible_platform'\n"
        "requests==2.28.0\n"
    )
    requirements_list = list(parse_requirements(str(requirements_path), mocker.Mock()))
    names = [r.name for r in requirements_list]
    assert "cryptography" in names
    assert "requests" in names
    assert "pywin32" not in names


def test_inactive_marker_with_unpinned_requirement(tmp_path, mocker):
    """Unpinned requirements are rejected even with inactive markers.

    pybuild-deps validates ALL requirements (including those with inactive
    markers) for cross-platform reproducibility. This ensures a requirements
    file is valid on all platforms, not just the current one.

    This differs from pip/pip-compile which filter markers before validation.
    """
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("foo>1 ; sys_platform == 'impossible_platform'")
    with pytest.raises(PyBuildDepsError, match="not exact"):
        list(parse_requirements(str(requirements_path), mocker.Mock()))
