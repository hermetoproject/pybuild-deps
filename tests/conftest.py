"""Shared fixtures."""

import zipfile
from pathlib import Path

import pytest


def _write_wheel(directory: Path, name: str, version: str, requires: list[str]):
    """Write a minimal wheel that carries only the metadata uv resolves from."""
    dist_info = f"{name}-{version}.dist-info"
    metadata = [f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"]
    metadata.extend(f"Requires-Dist: {req}\n" for req in requires)
    with zipfile.ZipFile(directory / f"{name}-{version}-py3-none-any.whl", "w") as whl:
        whl.writestr(f"{dist_info}/METADATA", "".join(metadata))
        whl.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        whl.writestr(f"{dist_info}/RECORD", "")


@pytest.fixture
def local_index(tmp_path: Path) -> list[str]:
    """Pip option lines pointing uv at an offline index of test wheels.

    ``backend`` requires ``helper>=2``. ``tool`` 2.0 requires ``helper>=3``
    while ``tool`` 1.0 takes any ``helper``. ``helper`` and ``plugin`` have no
    requirements and several versions each.
    """
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _write_wheel(wheels, "backend", "1.0", ["helper>=2"])
    _write_wheel(wheels, "tool", "1.0", ["helper"])
    _write_wheel(wheels, "tool", "2.0", ["helper>=3"])
    for version in ("1.0", "2.0", "3.0"):
        _write_wheel(wheels, "helper", version, [])
    for version in ("1.0", "2.0"):
        _write_wheel(wheels, "plugin", version, [])
    return ["--no-index", f"--find-links {wheels}"]
