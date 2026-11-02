"""Test cases for the __main__ module."""

import traceback
from os import chdir
from pathlib import Path

import pytest
from click.testing import CliRunner

from pybuild_deps import __main__ as main
from pybuild_deps.compile_build_dependencies import (
    BuildDependencyCompiler,
    ResolvedDependency,
)
from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.logger import log
from pybuild_deps.parsers import parse_requirements
from pybuild_deps.scripts.compile import PIP_UV_ENV


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
    # repeating the same test to cover the cached version
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
    expected_packages = {"setuptools-rust", "setuptools-scm"}
    build_requirements = list(parse_requirements(str(output)))
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


def test_compile_hashed_input_and_constraints(
    runner: CliRunner, tmp_path: Path, mocker
):
    """Hashed requirements parse; -c pins steer resolution without being built."""
    resolve = mocker.patch.object(BuildDependencyCompiler, "resolve", return_value=[])
    chdir(tmp_path)
    (tmp_path / "constraints.txt").write_text("cython==3.0.0\nsetuptools<70\n")
    (tmp_path / "requirements.txt").write_text(
        "-c constraints.txt\nidna==3.10 \\\n    --hash=sha256:aaa\n"
    )
    result = runner.invoke(main.cli, args=["compile"])
    assert result.exit_code == 0
    (requirements,), kwargs = resolve.call_args
    assert requirements == ["idna==3.10"]
    assert kwargs["pins"] == ["idna==3.10", "cython==3.0.0", "setuptools<70"]


@pytest.fixture
def fake_resolve(mocker, tmp_path):
    """Resolve to one dependency without network, from inside tmp_path."""
    chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("idna==3.10\n")
    return mocker.patch.object(
        BuildDependencyCompiler,
        "resolve",
        return_value=[
            ResolvedDependency(
                name="flit-core",
                version="3.12.0",
                hashes=("sha256:aaa",),
                via=frozenset({"idna"}),
            )
        ],
    )


@pytest.mark.parametrize(
    ("args", "command"),
    [
        (["-o", "out.txt"], "pybuild-deps compile --output-file=out.txt"),
        (
            ["-v", "--generate-hashes", "--output-file", "out.txt", "requirements.txt"],
            (
                "pybuild-deps compile --generate-hashes --output-file=out.txt "
                "requirements.txt"
            ),
        ),
        (
            ["--no-annotate", "--annotation-style=line", "-o", "out.txt"],
            (
                "pybuild-deps compile --annotation-style=line --no-annotate "
                "--output-file=out.txt"
            ),
        ),
    ],
)
def test_compile_header_command(runner, tmp_path, fake_resolve, args, command):
    """The header records a normalized command, like pip-compile did."""
    result = runner.invoke(main.cli, args=["compile", *args])
    assert result.exit_code == 0
    assert (tmp_path / "out.txt").read_text().splitlines()[4] == f"#    {command}"


def test_compile_custom_compile_command(runner, tmp_path, fake_resolve, monkeypatch):
    """CUSTOM_COMPILE_COMMAND replaces the command in the header."""
    monkeypatch.setenv("CUSTOM_COMPILE_COMMAND", "make build-deps")
    result = runner.invoke(main.cli, args=["compile", "-o", "out.txt"])
    assert result.exit_code == 0
    assert (tmp_path / "out.txt").read_text().splitlines()[4] == "#    make build-deps"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], "flit-core==3.12.0\n    # via idna\n"),
        (["--no-annotate"], "flit-core==3.12.0\n"),
        (["--annotation-style", "line"], "flit-core==3.12.0         # via idna\n"),
        (
            ["--generate-hashes"],
            "flit-core==3.12.0 \\\n    --hash=sha256:aaa\n    # via idna\n",
        ),
    ],
)
def test_compile_output_flags(runner, tmp_path, fake_resolve, args, expected):
    """Annotation and hash flags shape the written file."""
    result = runner.invoke(
        main.cli, args=["compile", "--no-header", "-o", "out.txt", *args]
    )
    assert result.exit_code == 0
    assert (tmp_path / "out.txt").read_text() == expected
    assert "flit-core==3.12.0" not in result.stderr


def test_compile_dry_run(runner, tmp_path, fake_resolve):
    """A dry run prints the result and writes nothing."""
    result = runner.invoke(
        main.cli, args=["compile", "--dry-run", "--no-header", "-o", "out.txt"]
    )
    assert result.exit_code == 0
    assert not (tmp_path / "out.txt").exists()
    assert "flit-core==3.12.0" in result.stderr.splitlines()


def test_compile_forwards_options(runner, tmp_path, fake_resolve):
    """Options from the requirements file reach the resolver and the output."""
    (tmp_path / "requirements.txt").write_text(
        "--extra-index-url https://example.com/simple\n--pre\nidna==3.10\n"
    )
    result = runner.invoke(main.cli, args=["compile", "--no-header", "-o", "out.txt"])
    assert result.exit_code == 0
    assert fake_resolve.call_args.kwargs["options"] == [
        "--extra-index-url https://example.com/simple",
        "--pre",
    ]
    output = (tmp_path / "out.txt").read_text()
    assert output.splitlines()[:2] == [
        "--extra-index-url https://example.com/simple",
        "",
    ]


@pytest.mark.parametrize(
    ("env", "warnings"),
    [
        ({}, 0),
        ({"PIP_INDEX_URL": "https://example.com/simple"}, 0),
        (
            {
                "PIP_EXTRA_INDEX_URL": "x",
                "PIP_FIND_LINKS": "y",
                "PIP_NO_CACHE_DIR": "1",
            },
            0,
        ),
    ],
)
def test_compile_handles_pip_env(runner, fake_resolve, mocker, env, warnings):
    """Pip index settings are bridged to uv, with conflicts warned about."""
    warning = mocker.spy(log, "warning")
    result = runner.invoke(
        main.cli,
        args=["compile", "-o", "out.txt"],
        env={**dict.fromkeys(PIP_UV_ENV), **env},
    )
    assert result.exit_code == 0
    assert warning.call_count == warnings


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
    build_requirements = list(parse_requirements(str(output)))
    names = {r.name for r in build_requirements}
    assert "setuptools-rust" in names
    assert "pywin32" not in names


@pytest.mark.e2e
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
