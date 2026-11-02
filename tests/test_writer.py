"""Tests for the requirements file writer."""

import sys
from pathlib import Path

import pytest

from pybuild_deps.compile_build_dependencies import ResolvedDependency
from pybuild_deps.writer import format_options, render


DATA = Path(__file__).parent / "data" / "writer"

# What pybuild-deps 0.6.1 (pip-tools) resolved for pluggy==1.5.0, the source of
# the files in DATA.
RESULTS = [
    ResolvedDependency(
        name="setuptools",
        version="84.0.0",
        hashes=(
            "sha256:f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73",
            "sha256:51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
        ),
        via=frozenset({"pluggy", "setuptools-scm", "vcs-versioning"}),
    ),
    ResolvedDependency(
        name="setuptools-scm",
        version="10.3.4",
        hashes=(
            "sha256:82f34c3e3084fc2b57d397200637cc13f2338004052d2fee47baa5f0e902464e",
            "sha256:a69f28bfc245608781205e912faae437c2b2165773afa4e7b979d77447a69dd2",
        ),
        via=frozenset({"pluggy"}),
    ),
    ResolvedDependency(
        name="packaging",
        version="26.3",
        hashes=(
            "sha256:94edc256424af38762eb31306eed28beb9f0efc50a8837492c9d6fd6004aed79",
            "sha256:d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c",
        ),
        via=frozenset({"setuptools-scm", "vcs-versioning"}),
    ),
    ResolvedDependency(
        name="vcs-versioning",
        version="2.6.0",
        hashes=(
            "sha256:22e9159288e2d8bca2fa6f6c31c34c9c66aec157f60e9e526f5d160d2516d60f",
            "sha256:f8bebd1302ebc12e67ceb30fc7dd698ec969414b6fa43b30c3f14ac9b1e72c41",
        ),
        via=frozenset({"setuptools-scm"}),
    ),
    ResolvedDependency(
        name="flit-core",
        version="4.1.0",
        hashes=(
            "sha256:62e12b63ead8335b37f59fabb977c7167fe476dafb5e41785dfa8c9aff843bc6",
            "sha256:17398cdd2c38b24047a5a9c93089ec5c0bf12ec3d1469bbf69c27ed7965299db",
        ),
        via=frozenset({"packaging"}),
    ),
]


def _expected(name: str) -> tuple[str, str]:
    """Return a file 0.6.1 wrote, with the header naming us, and its command."""
    text = (DATA / name).read_text()
    python = f"Python {sys.version_info.major}.{sys.version_info.minor}"
    text = text.replace("pip-compile with Python 3.12", f"pybuild-deps with {python}")
    return text, text.splitlines()[4][len("#    ") :]


def test_render_preserves_markers():
    """Render a dependency marker in the output requirement."""
    result = render(
        [
            ResolvedDependency(
                name="cffi", version="1.17.1", marker='python_version >= "3.8"'
            )
        ],
        compile_command=None,
        options=[],
        annotate=False,
        annotation_style="split",
        generate_hashes=False,
    )
    assert result == 'cffi==1.17.1 ; python_version >= "3.8"\n'


def test_render_preserves_direct_url():
    """Render direct URL resolutions as direct URL requirements."""
    result = render(
        [
            ResolvedDependency(
                name="demo", version="", url="file:///tmp/demo-1.0-py3-none-any.whl"
            )
        ],
        compile_command=None,
        options=[],
        annotate=False,
        annotation_style="split",
        generate_hashes=False,
    )
    assert result == "demo @ file:///tmp/demo-1.0-py3-none-any.whl\n"


@pytest.mark.parametrize(
    ("name", "annotate", "annotation_style", "generate_hashes"),
    [
        ("split.txt", True, "split", False),
        ("hashes.txt", True, "split", True),
        ("line.txt", True, "line", True),
        ("line_nohash.txt", True, "line", False),
        ("noann.txt", False, "split", False),
    ],
)
def test_render_matches_pip_compile(name, annotate, annotation_style, generate_hashes):
    """Output is what pip-tools wrote for the same results, header aside."""
    expected, command = _expected(name)
    output = render(
        RESULTS,
        compile_command=command,
        options=[],
        annotate=annotate,
        annotation_style=annotation_style,
        generate_hashes=generate_hashes,
    )
    assert output == expected


def test_render_without_header():
    """No compile command means no header."""
    expected = (DATA / "nohdr.txt").read_text()
    output = render(
        RESULTS,
        compile_command=None,
        options=[],
        annotate=True,
        annotation_style="split",
        generate_hashes=False,
    )
    assert output == expected


def test_render_options_and_versions():
    """Options lead the packages; versions of one package sort numerically."""
    results = [
        ResolvedDependency(name="Cython", version="3.0.11", via=frozenset({"lxml"})),
        ResolvedDependency(name="cython", version="0.29.37", via=frozenset({"pyyaml"})),
    ]
    output = render(
        results,
        compile_command=None,
        options=["--extra-index-url https://example.com/simple"],
        annotate=True,
        annotation_style="split",
        generate_hashes=False,
    )
    assert output == (
        "--extra-index-url https://example.com/simple\n"
        "\n"
        "cython==0.29.37\n"
        "    # via pyyaml\n"
        "cython==3.0.11\n"
        "    # via lxml\n"
    )


def test_render_empty():
    """Nothing to write still produces a file."""
    output = render(
        [],
        compile_command=None,
        options=[],
        annotate=True,
        annotation_style="split",
        generate_hashes=False,
    )
    assert output == "\n"


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ([], []),
        (["--index-url https://pypi.org/simple/"], []),
        (["-i https://example.com/simple"], ["--index-url https://example.com/simple"]),
        (
            ["--index-url=https://example.com/simple"],
            ["--index-url https://example.com/simple"],
        ),
        (
            ["--extra-index-url https://example.com/simple"],
            ["--extra-index-url https://example.com/simple"],
        ),
        (
            [
                "-i https://a.example/simple",
                "--extra-index-url https://b.example/simple",
                "--extra-index-url https://b.example/simple",
            ],
            [
                "--index-url https://a.example/simple",
                "--extra-index-url https://b.example/simple",
            ],
        ),
        (
            ["--no-index", "--extra-index-url https://b.example/simple", "-f ./wheels"],
            ["--find-links ./wheels"],
        ),
        (
            ["--trusted-host b.example", "--find-links https://b.example/links"],
            ["--find-links https://b.example/links", "--trusted-host b.example"],
        ),
        (
            ["--only-binary Foo_Bar,baz", "--no-binary :all:"],
            ["--no-binary :all:"],
        ),
        (
            ["--no-binary :all:", "--only-binary Foo_Bar,baz"],
            [
                "--no-binary :all:",
                "--only-binary baz",
                "--only-binary foo-bar",
            ],
        ),
        (["--no-binary :all:", "--no-binary :none:"], []),
        (["--pre", "--require-hashes", "--prefer-binary"], []),
    ],
)
def test_format_options(options, expected):
    """Record the options pip-compile recorded, the way pip combines them."""
    assert list(format_options(options)) == expected
