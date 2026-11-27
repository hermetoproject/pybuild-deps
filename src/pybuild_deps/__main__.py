"""Command-line interface."""

import sys

import click

from pybuild_deps.exceptions import PyBuildDepsError

from .finder import find_build_dependencies
from .logger import log
from .scripts import compile
from .scripts.list import list_build_deps


@click.group()
@click.version_option(package_name="pybuild-deps")
def cli() -> None:
    """Entrypoint for PyBuild Deps."""
    log.as_library = False  # pragma: no cover


@cli.command()
@click.argument("package-name")
@click.argument("package-version")
@click.option("-v", "--verbose", count=True, help="Show more output")
def find_build_deps(package_name, package_version, verbose):
    """Find build dependencies for given package."""
    log.verbosity = verbose

    try:
        deps = find_build_dependencies(
            package_name=package_name, version=package_version
        )
    except PyBuildDepsError as err:
        log.error(str(err))
        sys.exit(2)
    for dep in deps:
        click.echo(dep)


cli.add_command(list_build_deps, "list")
cli.add_command(compile.compile, "compile")

if __name__ == "__main__":
    cli(prog_name="pybuild-deps")  # pragma: no cover
