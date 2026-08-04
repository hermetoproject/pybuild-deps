"""Test cases for the __main__ module."""

import traceback
from os import chdir
from pathlib import Path

import pytest
from click.testing import CliRunner

from pybuild_deps import __main__ as main
from pybuild_deps.compile_build_dependencies import BuildDependencyCompiler
from pybuild_deps.exceptions import PyBuildDepsError


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


def test_main_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(main.cli, args=["--help"])
    assert result.exit_code == 0


@pytest.mark.e2e
@pytest.mark.parametrize(
    "package_name,version,expected_deps",
    [
        ("urllib3", "1.26.13", []),
        (
            "cryptography",
            "39",
            [
                "setuptools>=40.6.0,!=60.9.0",
                "wheel",
                "cffi>=1.12; platform_python_implementation != 'PyPy'",
                "setuptools-rust>=0.11.4",
            ],
        ),
        (
            "cryptography",
            "git+https://github.com/pyca/cryptography@41.0.5",
            [
                "setuptools>=61.0.0",
                "wheel",
                "cffi>=1.12; platform_python_implementation != 'PyPy'",
                "setuptools-rust>=0.11.4",
            ],
        ),
        (
            "cryptography",
            "https://github.com/pyca/cryptography/archive/refs/tags/43.0.0.tar.gz",
            [
                "maturin>=1,<2",
                "cffi>=1.12; platform_python_implementation != 'PyPy'",
                "setuptools",
            ],
        ),
        ("debugpy", "1.8.5", ["wheel", "setuptools"]),
    ],
)
def test_find_build_deps(
    cache: Path, runner: CliRunner, package_name, version, expected_deps
):
    """End to end testing for find-build-deps command."""
    assert not cache.exists()
    result = runner.invoke(main.cli, args=["find-build-deps", package_name, version])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == expected_deps
    assert cache.exists()
    result = runner.invoke(main.cli, args=["find-build-deps", package_name, version])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == expected_deps


@pytest.mark.e2e
@pytest.mark.parametrize(
    "package_name,version,expected_error",
    [
        (
            "grpcio",
            "1.59.0",
            "[ERROR]: Unable to parse setup.py for package grpcio==1.59.0.",
        ),
        (
            "some-package",
            "git+https://example.com",
            "[ERROR]: Unsupported requirement 'some-package @ git+https://example.com'. Requirement must be either pinned (==), a vcs link with sha or a direct url.",  # noqa: E501
        ),
        (
            "some-package",
            "https://example.com",
            "[ERROR]: Unable to unpack 'some-package @ https://example.com'. Is 'https://example.com' a python package?",  # noqa: E501
        ),
    ],
)
def test_find_build_deps_error(
    cache: Path, runner: CliRunner, package_name, version, expected_error
):
    """End to end testing for find-build-deps command."""
    assert not cache.exists()
    result = runner.invoke(main.cli, args=["find-build-deps", package_name, version])
    assert result.exit_code == 2
    assert result.stderr.splitlines()[-1] == expected_error


@pytest.mark.e2e
def test_find_build_deps_no_sdist(cache: Path, runner: CliRunner):
    """Test that packages without sdist are skipped gracefully."""
    assert not cache.exists()
    result = runner.invoke(main.cli, args=["find-build-deps", "tensorflow", "2.14.0"])
    assert result.exit_code == 0


@pytest.mark.e2e
def test_compile_greenpath(runner: CliRunner, tmp_path: Path):
    """Test happy path for compile command."""
    output = tmp_path / "requirements-build.txt"
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==39.0.0")
    result = runner.invoke(
        main.cli, args=["compile", str(requirements_path), "-o", str(output)]
    )
    assert result.exit_code == 0, traceback.print_tb(result.exc_info[2])
    content = output.read_text()
    names = {
        line.split("==")[0]
        for line in content.splitlines()
        if "==" in line and not line.startswith("#")
    }
    assert {"setuptools-rust", "setuptools-scm"}.issubset(names)


def test_compile_missing_requirements_txt(runner: CliRunner, tmp_path: Path):
    """Test compile without a requirements.txt."""
    chdir(tmp_path)
    result = runner.invoke(main.cli, args=["compile"])
    assert result.exit_code != 0
    err_message = result.stderr.splitlines()[-1]

    assert (
        err_message == "Error: Invalid value: Couldn't find a 'requirements.txt'."
        " You must specify at least one input file."
    )


@pytest.mark.e2e
@pytest.mark.parametrize("args", ["--no-header", "--generate-hashes"])
def test_compile_implicit_requirements_txt_and_non_default_options(
    runner: CliRunner,
    tmp_path: Path,
    cache: Path,
    args,
):
    """Exercise some options to ensure they are working."""
    chdir(tmp_path)
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("setuptools-rust==1.6.0")
    result = runner.invoke(main.cli, args=["compile", args])
    assert result.exit_code == 0
    assert {file.name for file in cache.glob("*") if file.is_dir()} == {
        "setuptools",
        "setuptools-rust",
    }


def test_compile_not_pinned_requirements_txt(runner: CliRunner, tmp_path: Path):
    """Ensure the appropriate error is thrown for non pinned requirements."""
    chdir(tmp_path)
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("setuptools-rust<1")
    result = runner.invoke(main.cli, args=["compile"])
    assert result.exit_code == 2
    assert "is not exact" in result.stderr.splitlines()[-1]


def test_compile_error_handling(runner: CliRunner, tmp_path: Path, mocker):
    """Test error handling for exceptions during resolution."""
    mocker.patch.object(
        BuildDependencyCompiler,
        "resolve",
        side_effect=PyBuildDepsError("SOME ERROR"),
    )
    chdir(tmp_path)
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("setuptools-rust==1.6.0")
    result = runner.invoke(main.cli, args=["compile"])
    assert result.exit_code == 2
    assert result.stderr.splitlines()[-1] == "[ERROR]: SOME ERROR"


def test_compile_unsolvable_dependencies(runner: CliRunner, tmp_path: Path, mocker):
    """Test CLI error output for conflicting build dependencies."""
    chdir(tmp_path)
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("foo==0.1.2")
    mocker.patch(
        "pybuild_deps.compile_build_dependencies.find_build_dependencies",
        return_value=["setuptools>=70", "setuptools<60"],
    )
    result = runner.invoke(main.cli, args=["compile", "-o", str(tmp_path / "out.txt")])
    assert result.exit_code == 2


@pytest.mark.e2e
@pytest.mark.parametrize("generate_hashes", [False, True])
def test_compile_inactive_environment_markers(
    runner: CliRunner, tmp_path: Path, generate_hashes: bool
):
    """Test compile with requirements having inactive environment markers."""
    output = tmp_path / "requirements-build.txt"
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("pywin32==311 ; sys_platform == 'impossible_platform'")
    args = ["compile", str(requirements_path), "-o", str(output)]
    if generate_hashes:
        args.append("--generate-hashes")
    result = runner.invoke(main.cli, args=args)
    assert result.exit_code == 0, result.output
    content = output.read_text()
    lines = [line for line in content.splitlines() if line and not line.startswith("#")]
    assert lines == []


@pytest.mark.e2e
def test_compile_mixed_active_inactive_markers(runner: CliRunner, tmp_path: Path):
    """Test compile with mix of active and inactive markers."""
    output = tmp_path / "requirements-build.txt"
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text(
        "cryptography==39.0.0 ; python_version >= '3.0'\n"
        "pywin32==311 ; sys_platform == 'impossible_platform'\n"
    )
    result = runner.invoke(
        main.cli, args=["compile", str(requirements_path), "-o", str(output)]
    )
    assert result.exit_code == 0, result.output
    content = output.read_text()
    names = {
        line.split("==")[0]
        for line in content.splitlines()
        if "==" in line and not line.startswith("#")
    }
    assert "setuptools-rust" in names
    assert "pywin32" not in names


@pytest.mark.e2e
def test_compile_consistent_ordering(runner: CliRunner, tmp_path: Path):
    """Test ensuring ordering is consistent in compile results."""
    chdir(tmp_path)
    requirements = ["lxml==5.3.0", "pyyaml==6.0.1"]
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("\n".join(requirements))
    outfile1 = tmp_path / "outfile1"
    result1 = runner.invoke(
        main.cli, args=["compile", "--no-header", "-o", str(outfile1)]
    )
    assert result1.exit_code == 0
    outfile2 = tmp_path / "outfile2"
    result2 = runner.invoke(
        main.cli, args=["compile", "--no-header", "-o", str(outfile2)]
    )
    assert result2.exit_code == 0
    assert outfile1.read_text() == outfile2.read_text()
