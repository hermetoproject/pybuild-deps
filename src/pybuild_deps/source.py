"""Get source code for a given package."""

from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
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
from urllib3.util.retry import Retry

from pybuild_deps.constants import CACHE_PATH
from pybuild_deps.exceptions import NoSDistError, PyBuildDepsError
from pybuild_deps.logger import log
from pybuild_deps.utils import is_supported_requirement


_VCS_SCHEMES = frozenset({"git+https", "git+http", "git+ssh", "git+file", "git"})
_RETRY = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])


def _is_vcs_scheme(scheme: str) -> bool:
    """Check whether the URL scheme is a VCS transport."""
    if scheme in _VCS_SCHEMES:
        return True
    if "+" in scheme:
        raise PyBuildDepsError(
            f"Unsupported VCS type '{scheme.split('+')[0]}'. Only git is supported."
        )
    return False


def get_package_source(
    package_name: str, version: str, pip_session: PipSession | None = None
) -> Path:
    """Get source code for a given package."""
    parsed_url = urlparse(version)
    is_url = all((parsed_url.scheme, parsed_url.netloc))

    if is_url:
        path = parsed_url.path[1:] if parsed_url.path else ""
        cached_path = (
            CACHE_PATH / package_name / parsed_url.scheme / parsed_url.netloc / path
        )
    else:
        cached_path = CACHE_PATH / package_name / version
    tarball_path = cached_path / "source.tar.gz"
    if tarball_path.exists():
        log.info("using cached version for package %s==%s", package_name, version)
        return tarball_path

    url = version if is_url else get_source_url_from_pypi(package_name, version)

    return _retrieve_and_save_source(
        package_name,
        url,
        tarball_path=tarball_path,
        pip_session=pip_session,
    )


def _retrieve_and_save_source(
    package_name: str,
    url: str,
    *,
    tarball_path: Path,
    pip_session: PipSession | None = None,
) -> Path:
    """Download or clone package source and repack as package_name.tar.gz.

    Normalizes the directory hierarchy so consumers always get a tarball
    with a top-level directory named after the package.
    """
    scheme = urlparse(url).scheme
    is_vcs = _is_vcs_scheme(scheme)

    tarball_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp_dir:
        if is_vcs:
            ireq = install_req_from_req_string(f"{package_name} @ {url}")
            if not is_supported_requirement(ireq):
                raise PyBuildDepsError(
                    f"Unsupported requirement '{ireq.req}'. Requirement must be "
                    "either pinned (==), a vcs link with sha or a direct url."
                )
            pip_session = pip_session or PipSession()
            pip_downloader = Downloader(pip_session, "")
            with global_tempdir_manager():
                try:
                    unpack_url(
                        ireq.link,
                        tmp_dir,
                        download=pip_downloader,
                        verbosity=0,
                    )
                except InstallationError as err:
                    raise PyBuildDepsError(
                        f"Unable to unpack '{ireq.req}'. "
                        f"Is '{ireq.link}' a python package?"
                    ) from err
        else:
            tmp_path = Path(tmp_dir)
            _download_archive(url, package_name, tmp_path)
            _extract_archive(tmp_path, url, package_name)

            if not any(tmp_path.iterdir()):
                raise NoSDistError(
                    f"No content extracted from '{package_name} @ {url}'"
                )

        with tarfile.open(tarball_path, "w:gz") as tarball:
            tarball.add(tmp_dir, arcname=package_name)

    return tarball_path


def _validate_archive_members(names: list[str], url: str) -> None:
    """Reject archives with path traversal or absolute paths."""
    for name in names:
        normalized = name.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise PyBuildDepsError(f"Unsafe path '{name}' in archive from '{url}'")


def _is_within_directory(directory: str, target: str) -> bool:
    """Check that target path is within extracted directory hierarchy."""
    abs_dir = os.path.realpath(directory)
    abs_target = os.path.realpath(target)
    return abs_target.startswith(abs_dir + os.sep)


def _download_archive(url: str, package_name: str, dest: Path) -> None:
    """Download an archive from URL to dest/.pybuild_archive."""
    with requests.Session() as session:
        session.mount("https://", requests.adapters.HTTPAdapter(max_retries=_RETRY))
        session.mount("http://", requests.adapters.HTTPAdapter(max_retries=_RETRY))
        try:
            response = session.get(url, stream=True, timeout=120)
            response.raise_for_status()
            with open(dest / ".pybuild_archive", "wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))
        except requests.RequestException as err:
            raise PyBuildDepsError(
                f"Failed to download '{package_name} @ {url}'. "
                f"Is '{url}' a python package?"
            ) from err


def _extract_archive(dest: Path, url: str, package_name: str) -> None:
    """Extract a downloaded archive with path safety checks."""
    tmp_archive = dest / ".pybuild_archive"
    extract_dir = dest / ".pybuild_extract"
    extract_dir.mkdir()

    if tarfile.is_tarfile(tmp_archive):
        with tarfile.open(tmp_archive) as tf:
            _validate_archive_members(tf.getnames(), url)
            try:
                # filter="data" strips unsafe metadata (ownership, setuid)
                # but is only available since Python 3.10.12 / 3.12
                tf.extractall(extract_dir, filter="data")
            except TypeError:
                # older Python: manually reject symlinks, devices, etc.
                safe = [m for m in tf.getmembers() if m.isfile() or m.isdir()]
                tf.extractall(extract_dir, members=safe)  # noqa: S202
    elif zipfile.is_zipfile(tmp_archive):
        with zipfile.ZipFile(tmp_archive) as zf:
            _validate_archive_members(zf.namelist(), url)
            for info in zf.infolist():
                fn = os.path.join(str(extract_dir), info.filename)
                if not _is_within_directory(str(extract_dir), fn):
                    raise PyBuildDepsError(
                        f"Unsafe path '{info.filename}' in archive from '{url}'"
                    )
                if info.filename.endswith("/"):
                    os.makedirs(fn, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(fn), exist_ok=True)
                    with zf.open(info.filename) as src, open(fn, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    else:
        raise PyBuildDepsError(
            f"Unable to unpack '{package_name} @ {url}'. Is '{url}' a python package?"
        )

    tmp_archive.unlink()
    _unwrap_root_dir(extract_dir, dest)


def _unwrap_root_dir(extract_dir: Path, dest: Path) -> None:
    """Move extracted content up if archive had a single root directory.

    PyPI sdists wrap content in a single pkg-1.0/ directory. Unwrap it
    so that the re-tarred cache entry has a consistent structure.
    """
    children = list(extract_dir.iterdir())
    source = extract_dir
    if len(children) == 1 and children[0].is_dir():
        source = children[0]
    for item in source.iterdir():
        shutil.move(str(item), str(dest / item.name))
    shutil.rmtree(extract_dir, ignore_errors=True)


def get_source_url_from_pypi(package_name: str, version: str) -> str:
    """Get url for source code for a given package on pypi."""
    with requests.Session() as session:
        session.mount("https://", requests.adapters.HTTPAdapter(max_retries=_RETRY))
        try:
            response = session.get(
                f"https://pypi.org/pypi/{package_name}/{version}/json",
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as err:
            raise PyBuildDepsError(
                f"Failed to look up '{package_name}=={version}' on PyPI"
            ) from err
    for url in response.json()["urls"]:  # pragma: no branch
        if url["python_version"] == "source":
            return url["url"]
    raise NoSDistError(
        f"PyPI doesn't have the source code for package {package_name}=={version}"
    )
