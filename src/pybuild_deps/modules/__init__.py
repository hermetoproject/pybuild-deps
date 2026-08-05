"""Module initialization. Injects bundled pip into sys.path."""

import sys
from pathlib import Path


def _inject_pip():
    """Add the bundled pip source to sys.path.

    Must run before any pip or pip-tools imports. Prepending to
    sys.path makes the bundled pip take priority over any
    installed version.
    """
    pip_src = str(Path(__file__).parent / "pip" / "src")
    if pip_src not in sys.path:
        sys.path.insert(0, pip_src)


_inject_pip()
