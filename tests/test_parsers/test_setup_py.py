"""Tests for setup.py parser."""

import pytest

from pybuild_deps.parsers import parse_setup_py


SIMPLE = """
from setuptools import setup

setup()
"""

SIMPLE_SETUPTOOLS = """
import setuptools

setuptools.setup()
"""

SIMPLE_NON_SETUPTOOLS = """
import s

def whatever(**kwargs):
    ...

s.setup()
whatever(foo="bar")
"""

SIMPLE_NO_SETUP_REQUIRES = """
from setuptools import setup

setup(foo="bar")
"""

DIRECT = """
from setuptools import setup

setup(
    "some arg",
    some_kw="kw",
    setup_requires=[
        "foo",  # comments should not be a problem
    ],
)
"""

DIRECT_SETUPTOOLS = """
import setuptools

setuptools.setup(
    setup_requires=["foo"]
)
"""

USING_CONSTANT = """
from setuptools import setup

SETUP_REQUIRES = [
    "bar",  # some comment
]

setup(
    setup_requires=SETUP_REQUIRES,
)
"""

NO_SETUP = """
def foo():
    ...
def bar():
    ...

foo()
bar()
"""

INDIRECT = """
from setuptools import setup
DEP = "baz"
SETUP_REQUIRES = [DEP]
setup(setup_requires=SETUP_REQUIRES)
"""

INDIRECT2 = """
from setuptools import setup
BAZ = "baz"
DEP = BAZ
SETUP_REQUIRES = [DEP]
setup(setup_requires=SETUP_REQUIRES)
"""

IMPORTED_DEPENDENCY = """
from setuptools import setup
from foo import bar
setup(setup_requires=bar)
"""

KWARGS_DICT = """
from setuptools import setup

kwargs = dict(setup_requires="foo")
setup(**kwargs)
"""
MULTIPLE_ASSIGNMENT = """
from setuptools import setup

# not sure why someone would do it like this
SETUP_REQUIRES, OTHER_CONSTANT = ["foo"], "bar"

setup(
    setup_requires=SETUP_REQUIRES,
)
"""


@pytest.mark.parametrize(
    "setup_py,expected_result",
    [
        (SIMPLE, []),
        (SIMPLE_NO_SETUP_REQUIRES, []),
        (SIMPLE_NON_SETUPTOOLS, []),
        (USING_CONSTANT, ["bar"]),
        (DIRECT, ["foo"]),
        (IMPORTED_DEPENDENCY, []),
        (INDIRECT, ["baz"]),
        (INDIRECT2, ["baz"]),
        (NO_SETUP, []),
        (SIMPLE_SETUPTOOLS, []),
        (DIRECT_SETUPTOOLS, ["foo"]),
        pytest.param(
            KWARGS_DICT,
            ["foo"],
            marks=pytest.mark.xfail(reason="not implemented"),
        ),
        pytest.param(
            MULTIPLE_ASSIGNMENT,
            ["foo"],
            marks=pytest.mark.xfail(reason="not implemented"),
        ),
    ],
)
def test_parse_setup_py(setup_py, expected_result):
    """Test setup.py parser."""
    assert parse_setup_py(setup_py) == expected_result
