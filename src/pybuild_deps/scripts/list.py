"""List declared build dependencies for requirements files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

import click
from pip._internal.exceptions import PipError
from pip._internal.network.session import PipSession

from pybuild_deps.build_dependencies import find_build_dependencies_for_requirements
from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.logger import log
from pybuild_deps.parsers import parse_requirements


@click.command("list", context_settings={"help_option_names": ("-h", "--help")})
@click.option("-v", "--verbose", count=True, help="Show more output")
@click.option("-q", "--quiet", count=True, help="Show less output")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
    help="Report format",
)
@click.option(
    "-o",
    "--output-file",
    type=click.File("w", encoding="utf-8", atomic=True, lazy=True),
    default="-",
    help="Output file name. Will write to stdout by default.",
)
@click.argument(
    "src_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, allow_dash=False),
)
def list_build_deps(
    verbose: int,
    quiet: int,
    output_format: str,
    output_file: TextIO,
    src_files: tuple[str, ...],
) -> None:
    """Report each input package's declared build dependencies.

    Read fully resolved requirements from SRC_FILES, defaulting to
    requirements.txt. Build dependency specifiers are preserved without
    pinning or recursive inspection.
    """
    log.verbosity = verbose - quiet
    if not src_files:
        if not Path("requirements.txt").is_file():
            raise click.BadParameter(
                "Couldn't find a 'requirements.txt'. "
                "You must specify at least one input file."
            )
        src_files = ("requirements.txt",)

    try:
        with PipSession() as session:
            requirements = [
                ireq
                for src_file in src_files
                for ireq in parse_requirements(src_file, session=session)
            ]
        results = find_build_dependencies_for_requirements(requirements)
    except (PipError, PyBuildDepsError) as err:
        log.error(str(err))
        raise click.exceptions.Exit(2) from err

    if output_format == "json":
        click.echo(json.dumps(results, indent=2), file=output_file)
    else:
        sections = []
        for requirement, dependencies in results.items():
            if dependencies is None:
                lines = ["  (source distribution unavailable)"]
            elif dependencies:
                lines = [f"  {dependency}" for dependency in dependencies]
            else:
                lines = ["  (no declared build dependencies found)"]
            sections.append("\n".join([f"{requirement}:", *lines]))
        click.echo("\n\n".join(sections), file=output_file, nl=bool(sections))
