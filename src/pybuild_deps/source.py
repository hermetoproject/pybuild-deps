"""Get source code for a given package."""

from __future__ import annotations

import logging
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import requests
from pip._internal.exceptions import InstallationError
from pip._internal.network.download import Downloader
from pip._internal.network.session import PipSession
from pip._internal.operations.prepare import unpack_url
from pip._internal.req.constructors import install_req_from_req_string
from pip._internal.utils.temp_dir import global_tempdir_manager

from pybuild_deps.constants import CACHE_PATH
from pybuild_deps.exceptions import PyBuildDepsError
from pybuild_deps.utils import is_supported_requirement


def get_package_source(
    package_name: str, version: str, pip_session: PipSession | None = None
) -> Path:
    """Get source code for a given package."""
    parsed_url = urlparse(version)
    is_url = all((parsed_url.scheme, parsed_url.netloc))

    if is_url:
        if parsed_url.path:
            path = parsed_url.path[1:]
        else:
            path = ""
        cached_path = (
            CACHE_PATH / package_name / parsed_url.scheme / parsed_url.netloc / path
        )
    else:
        cached_path = CACHE_PATH / package_name / version
    tarball_path = cached_path / "source.tar.gz"
    error_path = cached_path / "error.json"
    if tarball_path.exists():
        logging.info("using cached version for package %s==%s", package_name, version)
        return tarball_path

    elif error_path.exists():
        raise NotImplementedError()

    url = version if is_url else get_source_url_from_pypi(package_name, version)

    return retrieve_and_save_source_from_url(
        package_name,
        url,
        tarball_path=tarball_path,
        error_path=error_path,
        pip_session=pip_session,
    )


def retrieve_and_save_source_from_url(
    package_name: str,
    url: str,
    *,
    tarball_path: Path,
    error_path: Path,
    pip_session: PipSession = None,
):
    """Retrieve package source from URL."""
    ireq = install_req_from_req_string(f"{package_name} @ {url}")
    if not is_supported_requirement(ireq):
        raise PyBuildDepsError(
            f"Unsupported requirement '{ireq.req}'. Requirement must be either pinned "
            "(==), a vcs link with sha or a direct url."
        )

    pip_session = pip_session or PipSession()
    pip_downloader = Downloader(pip_session, "", 3)

    with global_tempdir_manager(), TemporaryDirectory() as tmp_dir:
        try:
            unpack_url(
                ireq.link,
                tmp_dir,
                download=pip_downloader,
                verbosity=0,
            )
        except InstallationError as err:
            raise PyBuildDepsError(
                f"Unable to unpack '{ireq.req}'. Is '{ireq.link}' a python package?"
            ) from err
        tarball_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball_path, "w:gz") as tarball:
            tarball.add(tmp_dir, arcname=package_name)
    return tarball_path


def get_source_url_from_pypi(package_name, version):
    """Get url for source code for a given package on pypi."""
    response = requests.get(
        f"https://pypi.org/pypi/{package_name}/{version}/json", timeout=10
    )
    response.raise_for_status()
    for url in response.json()["urls"]:  # pragma: no branch
        if url["python_version"] == "source":
            return url["url"]
    raise PyBuildDepsError(
        f"PyPI doesn't have the source code for package {package_name}=={version}"
    )
