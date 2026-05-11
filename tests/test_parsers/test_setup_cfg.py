"""Test parsing build requirements from setup.cfg."""

import pytest

from pybuild_deps.parsers import parse_setup_cfg


EXAMPLE_CFG = """
[metadata]
name = foo

[options]
# comments are not supported inside keywords
setup_requires =
    foo
    bar
"""

EXAMPLE_CFG_WITH_MARKER = """
[metadata]
name = foo

[options]
setup_requires =
    foo>=1.0,<10
    bar>=2.0; python_version>="3.8"
"""


EXAMPLE_CFG_WO_SETUP_REQUIRES = """
[metadata]
name = foo

[options]
install_requires =
    foo
    bar
"""

EXAMPLE_CFG_BLANK_LINES = """
[metadata]
name = foo

[options]
setup_requires =
    foo

    bar
"""

EXAMPLE_CFG_INLINE_SEMI = """
[metadata]
name = foo

[options]
setup_requires = foo; bar
"""

EXAMPLE_CFG_INLINE_MIXED = """
[metadata]
name = foo

[options]
setup_requires = foo; bar
    baz
"""


@pytest.mark.parametrize(
    "setup_cfg,expected_result",
    [
        (EXAMPLE_CFG, ["foo", "bar"]),
        (
            EXAMPLE_CFG_WITH_MARKER,
            ["foo>=1.0,<10", 'bar>=2.0; python_version>="3.8"'],
        ),
        (EXAMPLE_CFG_BLANK_LINES, ["foo", "bar"]),
        (EXAMPLE_CFG_WO_SETUP_REQUIRES, []),
        (EXAMPLE_CFG_INLINE_SEMI, ["foo", "bar"]),
        (EXAMPLE_CFG_INLINE_MIXED, ["foo", "bar", "baz"]),
    ],
)
def test_parse_setup_cfg(setup_cfg, expected_result):
    """Test parsing build requirements from setup.cfg."""
    assert parse_setup_cfg(setup_cfg) == expected_result
