"""custom logger for pybuild-deps."""

# ruff: noqa: D102

from __future__ import annotations

import logging
from typing import Any

import click
from piptools.logging import log as piptools_logger


logging.basicConfig()
_logger = logging.getLogger("pybuild-deps")


class Logger:
    """
    Custom logger for pybuild-deps.

    When invoked as a CLI, will use click to log messages. Otherwise
    will use default python logger.
    """

    def __init__(self, verbosity: int = 0):
        self._verbosity = verbosity
        self.as_library = True

    @property
    def verbosity(self):
        return self._verbosity

    @verbosity.setter
    def verbosity(self, value):
        self._verbosity = value
        if self._verbosity < 0:
            _logger.setLevel(logging.WARNING)
        if self._verbosity == 0:
            _logger.setLevel(logging.INFO)
        if self._verbosity >= 1:
            _logger.setLevel(logging.DEBUG)
        # keep piptools logger verbosity in sync with ours
        piptools_logger.verbosity = value

    def log(self, level: int, message: str, *args: Any, **kwargs: Any) -> None:
        if self.as_library:
            _logger.log(level, message, *args, **kwargs)
        else:
            self._cli_log(level, message, kwargs)

    def _cli_log(self, level, message, kwargs):
        kwargs.setdefault("err", True)
        if level >= logging.ERROR:
            kwargs.setdefault("fg", "red")
        elif level >= logging.WARNING:
            kwargs.setdefault("fg", "yellow")
        elif level >= logging.INFO and self.verbosity < 0:
            return
        elif level >= logging.DEBUG and self.verbosity < 1:
            return
        elif level <= logging.DEBUG and self.verbosity >= 1:
            kwargs.setdefault("fg", "blue")
        click.secho(f"[{logging.getLevelName(level)}]: {message}", **kwargs)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, message, *args, **kwargs)


log = Logger()
