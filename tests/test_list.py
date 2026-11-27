"""Tests for listing direct build dependencies from requirements files."""

import io
import json
import tarfile

import pytest
from click.testing import CliRunner

from pybuild_deps.__main__ import cli
from pybuild_deps.exceptions import NoSDistError, PyBuildDepsError
from pybuild_deps.parsers.setup_py import SetupPyParsingError


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def finder(mocker):
    """Mock package inspection without resolving build requirements."""
    return mocker.patch(
        "pybuild_deps.build_dependencies.find_build_dependencies", return_value=[]
    )


@pytest.fixture
def requirements_file(tmp_path):
    """Create a resolved input file."""
    path = tmp_path / "requirements.txt"
    path.write_text("foo==1.0\nbar==2.0\n")
    return path


def test_list_grouped_declarations(runner, requirements_file, finder):
    """Keep declarations and package attribution without walking build dependencies."""
    finder.side_effect = [
        ["setuptools>=64", "wheel", "cffi; sys_platform == 'other_platform'"],
        ["setuptools<64"],
    ]
    result = runner.invoke(cli, ["list", str(requirements_file)])
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "foo==1.0:\n"
        "  setuptools>=64\n"
        "  wheel\n"
        "  cffi; sys_platform == 'other_platform'\n"
        "\n"
        "bar==2.0:\n"
        "  setuptools<64\n"
    )
    assert [call.args for call in finder.call_args_list] == [
        ("foo", "1.0"),
        ("bar", "2.0"),
    ]


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize("destination", [None, "-", "report.txt"])
def test_list_output(
    runner, requirements_file, finder, tmp_path, output_format, destination
):
    """Write the same report to stdout or an explicitly selected file."""
    finder.side_effect = [["setuptools>=64"], []]
    args = ["list", str(requirements_file), "--format", output_format]
    if destination is not None:
        output = "-" if destination == "-" else str(tmp_path / destination)
        args.extend(["-o", output])
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    if destination == "report.txt":
        assert result.stdout == ""
        content = (tmp_path / destination).read_text()
    else:
        content = result.stdout
    if output_format == "json":
        assert json.loads(content) == {"foo==1.0": ["setuptools>=64"], "bar==2.0": []}
    else:
        assert content == (
            "foo==1.0:\n  setuptools>=64\n\n"
            "bar==2.0:\n  (no declared build dependencies found)\n"
        )


def test_list_default_input(runner, requirements_file, finder, monkeypatch):
    """Use requirements.txt when no input path is supplied."""
    monkeypatch.chdir(requirements_file.parent)
    result = runner.invoke(cli, ["list", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"foo==1.0": [], "bar==2.0": []}


def test_list_missing_default_input(runner, tmp_path, monkeypatch, finder):
    """Explain how to supply input when requirements.txt is absent."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 2
    assert "You must specify at least one input file." in result.stderr
    finder.assert_not_called()


def test_list_includes_constraints_and_duplicates(
    runner, requirements_file, finder, tmp_path
):
    """Inspect included requirements once and exclude constraint-only packages."""
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("constraint-only==3.0\n")
    included = tmp_path / "included.txt"
    included.write_text("foo==1.0\n")
    requirements_file.write_text(
        "-r included.txt\n-c constraints.txt\nfoo==1.0\nbar==2.0\n"
    )
    result = runner.invoke(
        cli,
        ["list", str(requirements_file), str(included), "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"foo==1.0": [], "bar==2.0": []}
    assert [call.args for call in finder.call_args_list] == [
        ("foo", "1.0"),
        ("bar", "2.0"),
    ]


def test_list_input_markers(runner, requirements_file, finder):
    """Skip inactive input packages while inspecting active packages."""
    requirements_file.write_text(
        "foo==1.0 ; python_version >= '3.0'\n"
        "bar==2.0 ; sys_platform == 'impossible_platform'\n"
    )
    result = runner.invoke(cli, ["list", str(requirements_file), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)) == 1
    finder.assert_called_once_with("foo", "1.0", raise_no_sdist_exc=True)


@pytest.mark.parametrize(
    "requirement",
    ["bar>=2", "bar>=2 ; sys_platform == 'impossible_platform'", "bar==2.*"],
)
def test_list_validates_before_inspection(
    runner, requirements_file, finder, requirement
):
    """Reject unresolved inputs before downloading or producing a partial report."""
    requirements_file.write_text(f"foo==1.0\n{requirement}\n")
    result = runner.invoke(cli, ["list", str(requirements_file)])
    assert result.exit_code == 2
    assert "only supports pinned dependencies" in result.stderr
    assert result.stdout == ""
    finder.assert_not_called()


def test_list_invalid_requirements_syntax(runner, requirements_file, finder):
    """Present pip parsing failures as CLI errors."""
    requirements_file.write_text("foo=>1\n")
    result = runner.invoke(cli, ["list", str(requirements_file)])
    assert result.exit_code == 2
    assert "[ERROR]" in result.stderr
    assert result.stdout == ""
    finder.assert_not_called()


@pytest.mark.parametrize(
    "url",
    ["https://example.com/foo-1.0.tar.gz", "git+https://example.com/foo.git@v1.0"],
)
def test_list_source_urls(runner, requirements_file, finder, url):
    """Forward supported source URLs to the finder without version resolution."""
    requirements_file.write_text(f"foo @ {url}\n")
    result = runner.invoke(cli, ["list", str(requirements_file), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {f"foo @ {url}": []}
    finder.assert_called_once_with("foo", url, raise_no_sdist_exc=True)


@pytest.mark.parametrize("error", [PyBuildDepsError, SetupPyParsingError])
def test_list_inspection_failure_preserves_output(
    runner, requirements_file, finder, tmp_path, error
):
    """Leave an existing report intact if any package cannot be inspected."""
    finder.side_effect = [["wheel"], error("Unable to inspect bar==2.0")]
    output = tmp_path / "report.json"
    output.write_text("previous report\n")
    result = runner.invoke(
        cli,
        ["list", str(requirements_file), "--format", "json", "-o", str(output)],
    )
    assert result.exit_code == 2
    assert "Unable to inspect bar==2.0" in result.stderr
    assert result.stdout == ""
    assert output.read_text() == "previous report\n"


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_list_missing_source(
    runner, requirements_file, mocker, tmp_path, output_format
):
    """Distinguish unavailable source from inspected packages with no declarations."""
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        root = tarfile.TarInfo("bar-2.0")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
    mocker.patch(
        "pybuild_deps.finder.get_package_source",
        side_effect=[NoSDistError("No source"), source],
    )
    result = runner.invoke(
        cli, ["list", str(requirements_file), "--format", output_format]
    )
    assert result.exit_code == 0, result.output
    assert "No source distribution found for foo==1.0" in result.stderr
    if output_format == "json":
        assert json.loads(result.stdout) == {"foo==1.0": None, "bar==2.0": []}
    else:
        assert result.stdout == (
            "foo==1.0:\n  (source distribution unavailable)\n\n"
            "bar==2.0:\n  (no declared build dependencies found)\n"
        )


@pytest.mark.parametrize(
    "files,expected",
    [
        (
            {"pyproject.toml": '[build-system]\nrequires = ["hatchling>=1"]\n'},
            ["hatchling>=1"],
        ),
        ({"setup.cfg": "[options]\nsetup_requires = wheel\n"}, ["wheel"]),
        (
            {
                "setup.py": (
                    'from setuptools import setup\nsetup(setup_requires=["Cython<3"])\n'
                )
            },
            ["Cython<3"],
        ),
        (
            {
                "pyproject.toml": '[build-system]\nrequires = ["setuptools>=64"]\n',
                "setup.cfg": "[options]\nsetup_requires = wheel\n",
                "setup.py": (
                    'from setuptools import setup\nsetup(setup_requires=["Cython<3"])\n'
                ),
            },
            ["setuptools>=64", "wheel", "Cython<3"],
        ),
    ],
)
def test_list_reads_source_declarations(
    runner, requirements_file, tmp_path, mocker, files, expected
):
    """Exercise the existing static parsers through the new command without network."""
    requirements_file.write_text("foo==1.0\n")
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode()
            member = tarfile.TarInfo(f"foo-1.0/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    mocker.patch("pybuild_deps.finder.get_package_source", return_value=source)
    result = runner.invoke(cli, ["list", str(requirements_file), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"foo==1.0": expected}


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_list_empty_input(runner, requirements_file, finder, output_format):
    """Produce an empty report without inspecting any packages."""
    requirements_file.write_text("# No requirements\n")
    result = runner.invoke(
        cli, ["list", str(requirements_file), "--format", output_format]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ("{}\n" if output_format == "json" else "")
    finder.assert_not_called()


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_list_empty_report_replaces_file(
    runner, requirements_file, finder, tmp_path, output_format
):
    """Replace a previous report when a successful inspection has no input packages."""
    requirements_file.write_text("")
    output = tmp_path / "report.txt"
    output.write_text("previous report\n")
    result = runner.invoke(
        cli,
        [
            "list",
            str(requirements_file),
            "--format",
            output_format,
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert output.read_text() == ("{}\n" if output_format == "json" else "")
    finder.assert_not_called()


def test_find_build_deps_missing_source_unchanged(runner, mocker):
    """Preserve the single-package command's handling of unavailable sources."""
    mocker.patch(
        "pybuild_deps.finder.get_package_source", side_effect=NoSDistError("No source")
    )
    result = runner.invoke(cli, ["find-build-deps", "foo", "1.0"])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "No source distribution found for foo==1.0" in result.stderr
