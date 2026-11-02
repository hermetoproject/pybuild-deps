"""compile script."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import IO, Any

import click
from click.utils import LazyFile
from packaging.requirements import Requirement

from pybuild_deps.compile_build_dependencies import BuildDependencyCompiler
from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.logger import log
from pybuild_deps.parsers import RequirementsFile, read_requirements_file
from pybuild_deps.writer import render


REQUIREMENTS_TXT = "requirements.txt"
# Options that don't change the result, left out of the header's command.
COMPILE_EXCLUDE_OPTIONS = {"--dry-run", "--quiet", "--verbose"}
# pip settings and their uv equivalents.
PIP_UV_ENV = {
    "PIP_INDEX_URL": "UV_INDEX_URL",
    "PIP_EXTRA_INDEX_URL": "UV_EXTRA_INDEX_URL",
    "PIP_FIND_LINKS": "UV_FIND_LINKS",
}


def get_compile_command(click_ctx: click.Context) -> str:
    """Get the normalized command for the header, the way pip-compile did.

    Long option names, no default values, sorted arguments, and no options
    that don't change the result, like --verbose.
    """
    params = {param.name: param for param in click_ctx.command.params}
    left_args = []
    right_args = []
    for name, value in click_ctx.params.items():
        param = params[name]
        if not isinstance(param, click.Option):
            # src_files; re-add the "--" click strips if any starts with "-"
            if any(val.startswith("-") and val != "-" for val in value):
                right_args.append("--")
            right_args.extend(shlex.quote(val) for val in value)
            continue
        long_name = param.opts[-1]
        negative = param.secondary_opts[-1] if param.secondary_opts else None
        if {long_name, negative} & COMPILE_EXCLUDE_OPTIONS:
            continue
        if value is None or value == param.default:
            continue
        if isinstance(value, LazyFile):
            value = value.name
        if param.is_flag:
            left_args.append(long_name if value else negative)
        else:
            left_args.append(f"{long_name}={shlex.quote(str(value))}")
    return " ".join(["pybuild-deps compile", *sorted(left_args), *sorted(right_args)])


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
    _warn_pip_env()

    parsed = [_read_requirements(src_file) for src_file in src_files]
    requirements = [_to_req_str(req) for f in parsed for req in f.requirements]
    # Input pins and all constraints steer resolution, but constraints do not
    # become build dependencies.
    pins = [
        _to_req_str(req) for f in parsed for req in f.requirements if _is_exact_pin(req)
    ]
    pins.extend(_to_req_str(req) for f in parsed for req in f.constraints)
    options = list(dict.fromkeys(line for f in parsed for line in f.options))

    compiler = BuildDependencyCompiler()
    try:
        results = compiler.resolve(
            requirements,
            pins=pins,
            options=options,
            generate_hashes=generate_hashes,
        )
    except PyBuildDepsError as e:
        log.error(str(e))
        sys.exit(2)

    compile_command = None
    if header:
        compile_command = os.environ.get(
            "CUSTOM_COMPILE_COMMAND"
        ) or get_compile_command(ctx)
    output = render(
        results,
        compile_command=compile_command,
        options=options,
        annotate=annotate,
        annotation_style=annotation_style,
        generate_hashes=generate_hashes,
    )
    if dry_run:
        click.echo(output, err=True, nl=False)
    if dry_run:
        log.info("Dry-run, so no file created/updated.")
    else:
        _get_stream(output_file).write(output.encode())


def _warn_pip_env() -> None:
    for pip_var, uv_var in PIP_UV_ENV.items():
        if os.environ.get(pip_var):
            if os.environ.get(uv_var):
                log.warning(f"Both {pip_var} and {uv_var} are set; using {uv_var}.")
            else:
                log.info(f"Using {pip_var} as {uv_var} for uv resolution.")
    if os.environ.get("PIP_NO_INDEX", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        log.info("Using PIP_NO_INDEX as --no-index for uv resolution.")


def _read_requirements(src_file: str) -> RequirementsFile:
    try:
        return read_requirements_file(src_file)
    except PyBuildDepsError as err:
        log.error(str(err))
        sys.exit(2)


def _to_req_str(req: Requirement) -> str:
    marker = f" ; {req.marker}" if req.marker else ""
    if req.url:
        return f"{req.name} @ {req.url}{marker}"
    return f"{req.name}{req.specifier}{marker}"


def _is_exact_pin(req: Requirement) -> bool:
    specs = list(req.specifier)
    return not req.url and len(specs) == 1 and specs[0].operator == "=="


def _get_stream(output_file: LazyFile | IO[Any]) -> IO[bytes]:
    if isinstance(output_file, LazyFile):
        return output_file.open()
    return output_file


def _handle_src_files():
    if Path(REQUIREMENTS_TXT).exists():
        src_files = (REQUIREMENTS_TXT,)
    else:
        raise click.BadParameter(
            f"Couldn't find a '{REQUIREMENTS_TXT}'. "
            "You must specify at least one input file."
        )

    return src_files
