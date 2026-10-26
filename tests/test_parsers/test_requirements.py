"""test requirements parser."""

from pathlib import Path

import pytest

from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.parsers import parse_requirements, read_requirements_file


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


@pytest.mark.parametrize(
    "line",
    [
        "package @ https://example.com/package-1.0.tar.gz",
        "package @ git+https://github.com/example/package.git@v1.0#subdirectory=src",
    ],
)
def test_pinned_direct_urls_are_supported(tmp_path, line):
    """Pinned direct and VCS URLs are accepted."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(line + "\n")
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].url


def test_unpinned_vcs_url_is_rejected(tmp_path):
    """A VCS URL without a revision is not reproducible."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "package @ git+https://github.com/example/package.git\n"
    )
    with pytest.raises(PyBuildDepsError):
        list(parse_requirements(str(requirements_path)))


def test_tab_separated_requirement_options(tmp_path):
    """Whitespace other than spaces separates requirement options."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("idna==3.10\t--hash=sha256:aaa\n")
    result = list(parse_requirements(str(requirements_path)))
    assert [str(requirement) for requirement in result] == ["idna==3.10"]


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


def test_include_cycle_is_rejected(tmp_path):
    """Recursive includes fail with a pybuild-deps error."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("-r requirements.txt\n")
    with pytest.raises(PyBuildDepsError):
        read_requirements_file(str(requirements_path))


def test_blank_lines_and_comments(tmp_path):
    """Blank lines and full-line comments are ignored."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "# this is a comment\n\nrequests==2.28.0\n\n# another comment\n"
    )
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert result[0].name == "requests"


@pytest.mark.parametrize(
    "content",
    [
        "idna==3.10 --hash=sha256:aaa\n",
        "idna==3.10 \\\n    --hash=sha256:aaa \\\n    --hash=sha256:bbb\n",
        # pip-compile and uv pip compile output, with an annotation
        "idna==3.10 \\\n    --hash=sha256:aaa\n    # via requests\n",
        "idna==3.10 ; python_version >= '3.0' \\\n    --hash=sha256:aaa\n",
        "idna==3.10 --config-settings=foo=bar\n",
    ],
)
def test_per_requirement_options_ignored(tmp_path, content):
    """Per-requirement options like --hash don't break parsing."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(content)
    result = list(parse_requirements(str(requirements_path)))
    assert len(result) == 1
    assert (result[0].name, str(result[0].specifier)) == ("idna", "==3.10")


@pytest.mark.parametrize(
    "include",
    ["-r base.txt", "-rbase.txt", "--requirement base.txt", "--requirement=base.txt"],
)
def test_requirement_include_forms(tmp_path, include):
    """Every spelling of -r is followed, relative to the including file."""
    (tmp_path / "base.txt").write_text("requests==2.28.0\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    main = sub / "requirements.txt"
    main.write_text(f"{include.replace('base.txt', '../base.txt')}\nidna==3.10\n")
    result = read_requirements_file(str(main))
    assert [r.name for r in result.requirements] == ["requests", "idna"]
    assert result.constraints == []
    assert result.options == []


@pytest.mark.parametrize(
    "include", ["-c c.txt", "-cc.txt", "--constraint c.txt", "--constraint=c.txt"]
)
def test_constraint_include_forms(tmp_path, include):
    """Constraint files only contribute pins, never requirements to build."""
    (tmp_path / "c.txt").write_text("-r nested.txt\nsetuptools<70\n")
    (tmp_path / "nested.txt").write_text("cython==3.0.0\n")
    main = tmp_path / "requirements.txt"
    main.write_text(f"{include}\nidna==3.10\n")
    result = read_requirements_file(str(main))
    assert [r.name for r in result.requirements] == ["idna"]
    assert [str(r) for r in result.constraints] == ["cython==3.0.0", "setuptools<70"]


def test_options_collected(tmp_path):
    """Global option lines are kept in order, once, across included files."""
    (tmp_path / "base.txt").write_text(
        "--extra-index-url https://example.com/simple\n--no-binary :all:\n"
    )
    main = tmp_path / "requirements.txt"
    main.write_text(
        "-i https://example.com/simple\n"
        "-r base.txt\n"
        "--extra-index-url https://example.com/simple\n"
        "idna==3.10\n"
    )
    result = read_requirements_file(str(main))
    assert result.options == [
        "-i https://example.com/simple",
        "--extra-index-url https://example.com/simple",
        "--no-binary :all:",
    ]
    assert [r.name for r in result.requirements] == ["idna"]


@pytest.mark.parametrize(
    "line", ["-e git+https://github.com/kjd/idna@v3.10#egg=idna", "--editable ."]
)
def test_editable_rejected(tmp_path, line):
    """Editable requirements raise a clear error."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text(f"{line}\n")
    with pytest.raises(PyBuildDepsError):
        read_requirements_file(str(requirements_path))


def test_missing_include(tmp_path):
    """A missing included file raises PyBuildDepsError."""
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("-r missing.txt\n")
    with pytest.raises(PyBuildDepsError):
        read_requirements_file(str(requirements_path))


def test_env_var_expanded(tmp_path, monkeypatch):
    """${VAR} is expanded like pip does."""
    monkeypatch.setenv("IDX", "https://example.com/simple")
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("--index-url ${IDX}\nidna==3.10\n")
    options = read_requirements_file(str(requirements_path)).options
    assert options == ["--index-url https://example.com/simple"]


def test_unset_env_var_left_alone(tmp_path, monkeypatch):
    """An unset ${VAR} stays as written, like pip."""
    monkeypatch.delenv("IDX", raising=False)
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("--index-url ${IDX}\nidna==3.10\n")
    options = read_requirements_file(str(requirements_path)).options
    assert options == ["--index-url ${IDX}"]
