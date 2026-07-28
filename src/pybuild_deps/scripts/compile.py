"""compile script."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

import click
from click.utils import LazyFile
from pip._internal.req import InstallRequirement
from piptools.exceptions import PipToolsError
from piptools.repositories import PyPIRepository
from piptools.utils import get_compile_command as _get_compile_command
from piptools.utils import (
    key_from_ireq,
)
from piptools.writer import OutputWriter as PipToolsWriter

from pybuild_deps.compile_build_dependencies import (
    BuildDependencyCompiler,
)
from pybuild_deps.constants import PIPTOOLS_CACHE_DIR
from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.logger import log
from pybuild_deps.parsers import parse_requirements
from pybuild_deps.utils import get_version


REQUIREMENTS_TXT = "requirements.txt"


def get_compile_command(click_ctx):
    """Get pip-compile equivalent command and adjust for pybuild-deps."""
    command = _get_compile_command(click_ctx)
    # this is just overriding the command for reproducibility. pip-compile will still
    # get credits since it will be displayed in the top of the header.
    return command.replace("pip-compile", "pybuild-deps compile")


@click.command(context_settings={"help_option_names": ("-h", "--help")})
@click.version_option(package_name="pybuild-deps")
@click.pass_context
@click.option("-v", "--verbose", count=True, help="Show more output")
@click.option("-q", "--quiet", count=True, help="Show less output")
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    help="Only show what would happen, don't change anything.",
)
@click.option(
    "--header/--no-header",
    is_flag=True,
    default=True,
    help="Add header to generated file",
)
@click.option(
    "--annotate/--no-annotate",
    is_flag=True,
    default=True,
    help="Annotate results, indicating where dependencies come from",
)
@click.option(
    "--annotation-style",
    type=click.Choice(("line", "split")),
    default="split",
    help="Choose the format of annotation comments",
)
@click.option(
    "-o",
    "--output-file",
    nargs=1,
    default=None,
    type=click.File("w+b", atomic=True, lazy=True),
    help=("Output file name. Will write to stdout by default."),
)
@click.option(
    "--generate-hashes",
    is_flag=True,
    default=False,
    help="Generate pip 8 style hashes in the resulting requirements file.",
)
@click.argument("src_files", nargs=-1, type=click.Path(exists=True, allow_dash=False))
def compile(
    ctx: click.Context,
    verbose: int,
    quiet: int,
    dry_run: bool,
    header: bool,
    annotate: bool,
    annotation_style: str,
    output_file: LazyFile | IO[Any] | None,
    generate_hashes: bool,
    src_files: tuple[str, ...],
) -> None:
    """Compiles build-requirements.txt from requirements.txt."""
    log.verbosity = verbose - quiet
    if len(src_files) == 0:
        src_files = _handle_src_files()
    if not output_file and not dry_run:
        log.warning("No output file (-o) specified. Defaulting to 'dry run' mode.")
        dry_run = True

    repository = PyPIRepository([], cache_dir=PIPTOOLS_CACHE_DIR)

    dependencies: list[InstallRequirement] = []
    for src_file in src_files:
        dependencies.extend(_parse_requirements(repository, src_file))

    compiler = BuildDependencyCompiler(repository)
    try:
        results = compiler.resolve(dependencies)
        hashes = None
        if compiler.resolver is not None and generate_hashes:
            hashes = compiler.resolver.resolve_hashes(results)
    except (PipToolsError, PyBuildDepsError) as e:
        log.error(str(e))
        sys.exit(2)

    if header:
        pybuild_deps_cmd = get_compile_command(ctx)
        os.environ.setdefault("CUSTOM_COMPILE_COMMAND", pybuild_deps_cmd)

    writer = OutputWriter(
        cast(BinaryIO, output_file),
        click_ctx=ctx,
        dry_run=dry_run,
        emit_header=header,
        emit_index_url=True,
        emit_trusted_host=True,
        annotate=annotate,
        annotation_style=annotation_style,
        strip_extras=True,
        generate_hashes=generate_hashes,
        default_index_url=repository.DEFAULT_INDEX_URL,
        index_urls=repository.finder.index_urls,
        trusted_hosts=repository.finder.trusted_hosts,
        format_control=repository.finder.format_control,
        linesep="\n",
        allow_unsafe=True,
        find_links=repository.finder.find_links,
        emit_find_links=True,
        emit_options=True,
    )
    unsafe_packages = None
    unsafe_requirements = None
    if compiler.resolver is not None:
        unsafe_packages = compiler.resolver.unsafe_packages
        unsafe_requirements = compiler.resolver.unsafe_constraints
    writer.write(
        results=results,
        unsafe_packages=unsafe_packages,
        unsafe_requirements=unsafe_requirements,
        markers={
            key_from_ireq(ireq): ireq.markers for ireq in dependencies if ireq.markers
        },
        hashes=hashes,
    )

    if dry_run:
        log.info("Dry-run, so no file created/updated.")


def _parse_requirements(repository, src_file):
    try:
        return list(
            parse_requirements(
                src_file,
                finder=repository.finder,
                session=repository.session,
                options=repository.options,
            )
        )
    except PyBuildDepsError as err:
        log.error(str(err))
        sys.exit(2)


def _handle_src_files():
    if Path(REQUIREMENTS_TXT).exists():
        src_files = (REQUIREMENTS_TXT,)
    else:
        raise click.BadParameter(
            f"Couldn't find a '{REQUIREMENTS_TXT}'. "
            "You must specify at least one input file."
        )

    return src_files


class OutputWriter(PipToolsWriter):
    """pip-tools OutputWriter with customizations for pybuild-deps."""

    def _sort_key(self, ireq: InstallRequirement) -> tuple[bool, str]:
        return (not ireq.editable, f"{ireq.name}=={get_version(ireq)}")
