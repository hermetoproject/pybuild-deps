"""Test cases for the __main__ module."""

import traceback
from os import chdir
from pathlib import Path

import pytest
from click.testing import CliRunner
from piptools.exceptions import PipToolsError
from piptools.repositories import PyPIRepository

from pybuild_deps import __main__ as main
from pybuild_deps.compile_build_dependencies import BuildDependencyCompiler
from pybuild_deps.constants import PIPTOOLS_CACHE_DIR
from pybuild_deps.parsers import parse_requirements


@pytest.fixture
def pypi_repo():
    """PyPIRepository instance for testing."""
    return PyPIRepository([], cache_dir=PIPTOOLS_CACHE_DIR)


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
        ("azure-identity", "1.14.1", []),
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
    # repeating the same test to cover the cached version
    result = runner.invoke(main.cli, args=["find-build-deps", package_name, version])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == expected_deps


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
        (
            "cryptography",
            "git+https://github.com/pyca/cryptography",
            "[ERROR]: Unsupported requirement 'cryptography @ git+https://github.com/pyca/cryptography'. Requirement must be either pinned (==), a vcs link with sha or a direct url.",  # noqa: E501
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
def test_compile_greenpath(
    runner: CliRunner, tmp_path: Path, pypi_repo: PyPIRepository
):
    """Test happy path for compile command."""
    output = tmp_path / "requirements-build.txt"
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("cryptography==39.0.0")
    result = runner.invoke(
        main.cli, args=["compile", str(requirements_path), "-o", str(output)]
    )
    assert result.exit_code == 0, traceback.print_tb(result.exc_info[2])
    expected_packages = {"setuptools-rust", "setuptools-scm"}
    build_requirements = list(parse_requirements(str(output), pypi_repo.session))
    assert expected_packages.issubset({r.name for r in build_requirements})


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
@pytest.mark.parametrize("args", ["--no-header", "--generate-hashes", "-v", "-q"])
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
    assert (
        result.stderr.splitlines()[-1]
        == "[ERROR]: requirement 'setuptools-rust<1 (from -r "
        "requirements.txt (line 1))' is not exact "
        "(pybuild-tools only supports pinned dependencies)."
    )


def test_compile_piptools_error(runner: CliRunner, tmp_path: Path, mocker):
    """Test error handling for exceptions raised by pip-tools."""
    mocker.patch.object(
        BuildDependencyCompiler, "resolve", side_effect=PipToolsError("SOME ERROR")
    )
    chdir(tmp_path)
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("setuptools-rust==1.6.0")
    result = runner.invoke(main.cli, args=["compile"])
    assert result.exit_code == 2
    assert result.stderr.splitlines()[-1] == "[ERROR]: SOME ERROR"


def test_compile_unsolvable_dependencies(runner: CliRunner, tmp_path: Path, mocker):
    """Test error handling for exceptions raised by pip-tools."""
    chdir(tmp_path)
    requirements = ["foo==0.1.2"]
    requirements_path: Path = tmp_path / "requirements.txt"
    requirements_path.write_text("\n".join(requirements))
    outfile = tmp_path / "outfile"
    mocker.patch(
        "pybuild_deps.compile_build_dependencies.find_build_dependencies",
        return_value=["setuptools>=42", "setuptools<42"],
    )
    result = runner.invoke(main.cli, args=["compile", "-o", str(outfile)])
    assert result.exit_code == 2
    assert (
        "Impossible to resolve the following dependencies for package 'foo==0.1.2'"
        in result.stderr
    )
    assert "setuptools>=42" in result.stderr
    assert "setuptools<42" in result.stderr


def test_compile_consistent_ordering(runner: CliRunner, tmp_path: Path):
    """Test ensuring ordering is consistent in compile results."""
    chdir(tmp_path)
    # these dependencies were the minimalist example I found to reproduce the ordering
    # issue. lxml depends on Cython>=3.0.11, while pyyaml depends on Cython<3.0. This
    # causes the resolution of 2 distinct versions of Cython which, without the bugfix,
    # will appear in a random order in the output file
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
