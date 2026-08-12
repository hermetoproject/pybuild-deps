"""Tests for pip-tools OutputWriter compatibility in compile."""

from __future__ import annotations

import inspect
import io
from typing import Any
from unittest.mock import MagicMock

import click
import pytest
from pip._internal.models.format_control import FormatControl
from piptools.writer import OutputWriter as PipToolsWriter

from pybuild_deps.scripts import compile as compile_module
from pybuild_deps.scripts.compile import OutputWriter, _piptools_output_writer_accepts_generate_hashes


@pytest.fixture
def output_writer_kwargs() -> dict[str, Any]:
    """Minimal kwargs for constructing OutputWriter in tests."""
    ctx = click.Context(click.Command("compile"))
    return {
        "dst_file": io.BytesIO(),
        "click_ctx": ctx,
        "dry_run": True,
        "emit_header": True,
        "emit_index_url": True,
        "emit_trusted_host": True,
        "annotate": True,
        "annotation_style": "split",
        "strip_extras": True,
        "default_index_url": "https://pypi.org/simple",
        "index_urls": ["https://pypi.org/simple"],
        "trusted_hosts": [],
        "format_control": FormatControl(set(), set()),
        "linesep": "\n",
        "allow_unsafe": True,
        "find_links": [],
        "emit_find_links": True,
        "emit_options": True,
    }


def test_piptools_output_writer_accepts_generate_hashes_matches_signature() -> None:
    """Helper reflects the installed pip-tools OutputWriter constructor."""
    assert _piptools_output_writer_accepts_generate_hashes() == (
        "generate_hashes" in inspect.signature(PipToolsWriter.__init__).parameters
    )


@pytest.mark.parametrize("generate_hashes", [False, True])
def test_output_writer_init_forwards_generate_hashes_when_supported(
    mocker,
    output_writer_kwargs: dict[str, Any],
    generate_hashes: bool,
) -> None:
    """Older pip-tools versions still require generate_hashes on OutputWriter."""
    mocker.patch.object(
        compile_module,
        "_piptools_output_writer_accepts_generate_hashes",
        return_value=True,
    )
    super_init = mocker.patch.object(PipToolsWriter, "__init__", return_value=None)

    OutputWriter(**output_writer_kwargs, generate_hashes=generate_hashes)

    assert super_init.call_args.kwargs["generate_hashes"] is generate_hashes


@pytest.mark.parametrize("generate_hashes", [False, True])
def test_output_writer_init_omits_generate_hashes_when_unsupported(
    mocker,
    output_writer_kwargs: dict[str, Any],
    generate_hashes: bool,
) -> None:
    """pip-tools 7.6.1+ dropped the unused generate_hashes constructor argument."""
    mocker.patch.object(
        compile_module,
        "_piptools_output_writer_accepts_generate_hashes",
        return_value=False,
    )
    super_init = mocker.patch.object(PipToolsWriter, "__init__", return_value=None)

    OutputWriter(**output_writer_kwargs, generate_hashes=generate_hashes)

    assert "generate_hashes" not in super_init.call_args.kwargs


def test_compile_passes_generate_hashes_flag_to_output_writer(
    mocker,
    tmp_path,
) -> None:
    """compile should construct OutputWriter even when --generate-hashes is set."""
    from click.testing import CliRunner

    from pybuild_deps import __main__ as main

    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("setuptools-rust==1.6.0")
    output_path = tmp_path / "requirements-build.txt"

    mock_resolver = MagicMock()
    mock_resolver.unsafe_packages = set()
    mock_resolver.unsafe_constraints = set()
    mock_resolver.resolve_hashes.return_value = {}

    mock_compiler = MagicMock()
    mock_compiler.resolve.return_value = set()
    mock_compiler.resolver = mock_resolver

    output_writer_init = mocker.patch.object(
        compile_module.OutputWriter,
        "__init__",
        return_value=None,
    )
    mocker.patch.object(compile_module.OutputWriter, "write")
    mocker.patch.object(
        compile_module.BuildDependencyCompiler,
        "__new__",
        return_value=mock_compiler,
    )

    result = CliRunner().invoke(
        main.cli,
        args=["compile", str(requirements_path), "-o", str(output_path), "--generate-hashes"],
    )

    assert result.exit_code == 0, result.output
    assert output_writer_init.call_args.kwargs["generate_hashes"] is True
