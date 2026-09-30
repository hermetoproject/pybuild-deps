"""test requirements parser."""

from pathlib import Path

import pytest

from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.parsers import parse_requirements


def test_pinned_requirements(tmp_path):
    """Test parsing requirements with pinned dependencies."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==40.0.0")
    requirements_list = list(parse_requirements(str(requirements_path)))
    assert [r.name for r in requirements_list] == ["cryptography"]


def test_unpinned_requirements(tmp_path):
    """Test parsing requirements with unpinned dependencies."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography>40")
    with pytest.raises(PyBuildDepsError):
        list(parse_requirements(str(requirements_path)))


def test_inactive_environment_markers(tmp_path):
    """Test that requirements with inactive environment markers are filtered."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("pywin32==311 ; sys_platform == 'impossible_platform'")
    requirements_list = list(parse_requirements(str(requirements_path)))
    assert requirements_list == []


def test_active_environment_markers(tmp_path):
    """Test that requirements with active environment markers are kept."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==40.0.0 ; python_version >= '3.0'")
    requirements_list = list(parse_requirements(str(requirements_path)))
    assert len(requirements_list) == 1
    assert requirements_list[0].name == "cryptography"


def test_mixed_markers(tmp_path):
    """Test mixed active and inactive markers."""
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "cryptography==40.0.0 ; python_version >= '3.0'\n"
        "pywin32==311 ; sys_platform == 'impossible_platform'\n"
        "requests==2.28.0\n"
    )
    requirements_list = list(parse_requirements(str(requirements_path)))
    names = [r.name for r in requirements_list]
    assert "cryptography" in names
    assert "requests" in names
    assert "pywin32" not in names


def test_inactive_marker_with_unpinned_requirement(tmp_path):
    """Unpinned requirements are rejected even with inactive markers.

    pybuild-deps validates ALL requirements (including those with inactive
    markers) for cross-platform reproducibility. This ensures a requirements
    file is valid on all platforms, not just the current one.

    This differs from pip/pip-compile which filter markers before validation.
    """
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("foo>1 ; sys_platform == 'impossible_platform'")
    with pytest.raises(PyBuildDepsError):
        list(parse_requirements(str(requirements_path)))


def test_line_continuations(tmp_path):
    """Line continuations are joined before parsing."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "cryptography==40.0.0 \\\n    ; python_version >= '3.0'\n"
    )
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].name == "cryptography"


def test_inline_comments(tmp_path):
    """Inline comments are stripped."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("requests==2.28.0  # pinned for compat\n")
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].name == "requests"


def test_r_includes(tmp_path):
    """Recursive -r includes are followed."""
    base = tmp_path / "base.txt"
    base.write_text("requests==2.28.0\n")
    main = tmp_path / "requirements.txt"
    main.write_text(f"-r {base}\ncryptography==40.0.0\n")
    result = list(parse_requirements(str(main)))
    names = [r.name for r in result]
    assert names == ["requests", "cryptography"]


def test_constraints_and_options_skipped(tmp_path):
    """Constraint files and pip options are silently skipped."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "-c constraints.txt\n--index-url https://pypi.org/simple\nrequests==2.28.0\n"
    )
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].name == "requests"


def test_blank_lines_and_comments(tmp_path):
    """Blank lines and full-line comments are ignored."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "# this is a comment\n\nrequests==2.28.0\n\n# another comment\n"
    )
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].name == "requests"
