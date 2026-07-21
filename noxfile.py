"""Nox sessions."""

import os
import shutil
import sys
from pathlib import Path
from textwrap import dedent

import nox


try:
    from nox_poetry import Session, session
except ImportError:
    message = f"""\
    Nox failed to import the 'nox-poetry' package.

    Please install it using the following command:

    {sys.executable} -m pip install nox-poetry"""
    raise SystemExit(dedent(message)) from None


package = "pybuild_deps"
python_versions = ["3.13", "3.12", "3.11", "3.10"]
nox.options.sessions = (
    "pre-commit",
    "tests",
    "docs-build",
)
nox.options.reuse_venv = "always"
test_requirements = ["pytest", "pytest-cov", "pytest-mock", "pytest-xdist"]



@session(name="pre-commit", python=python_versions[0])
def precommit(session: Session) -> None:
    """Lint using pre-commit."""
    args = session.posargs or [
        "run",
        "--all-files",
        "--hook-stage=manual",
        "--show-diff-on-failure",
    ]
    session.install(
        "ruff",
        "pre-commit",
        "pre-commit-hooks",
        "pydoclint",
    )
    session.run("pre-commit", *args)


@session(python=python_versions)
def tests(session: Session) -> None:
    """Run unit tests (excludes e2e tests that require network access)."""
    session.install(".")
    session.install(*test_requirements)
    args = ["-m", "not e2e"]
    if not session.posargs:
        args += [
            "--cov=pybuild_deps",
            "--cov-report=term",
            "--cov-report=xml",
            "--no-cov-on-fail",
        ]
    session.run("pytest", *args, *session.posargs)


@session(name="e2e-tests", python=python_versions[0])
def e2e_tests(session: Session) -> None:
    """Run e2e tests that require network access (single Python version, parallel)."""
    session.install(".")
    session.install(*test_requirements)
    session.run("pytest", "-m", "e2e", "-n", "auto", *session.posargs)


@session(name="docs-build", python=python_versions[0])
def docs_build(session: Session) -> None:
    """Build the documentation."""
    args = session.posargs or ["docs", "docs/_build"]
    if not session.posargs and "FORCE_COLOR" in os.environ:
        args.insert(0, "--color")

    session.install(".")
    session.install("sphinx", "sphinx-click", "furo", "myst-parser")

    build_dir = Path("docs", "_build")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("sphinx-build", *args)


@session(python=python_versions[0])
def docs(session: Session) -> None:
    """Build and serve the documentation with live reloading on file changes."""
    args = session.posargs or ["--open-browser", "docs", "docs/_build"]
    session.install(".")
    session.install("sphinx", "sphinx-autobuild", "sphinx-click", "furo", "myst-parser")

    build_dir = Path("docs", "_build")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("sphinx-autobuild", *args)
