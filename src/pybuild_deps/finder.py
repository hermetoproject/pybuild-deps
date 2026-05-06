"""Find build dependencies of a python package."""

from __future__ import annotations

import tarfile

from pip._internal.network.session import PipSession

from .cache import persistent_cache
from .exceptions import NoSDistError
from .logger import log
from .parsers import parse_pyproject_toml, parse_setup_cfg, parse_setup_py
from .parsers.setup_py import SetupPyParsingError
from .source import get_package_source


@persistent_cache("find-build-deps", ignore_kwargs=["pip_session"])
def find_build_dependencies(
    package_name,
    version,
    raise_setuppy_parsing_exc=True,
    pip_session: PipSession | None = None,
) -> list[str]:
    """Find build dependencies for a given package."""
    file_parser_map = {
        "pyproject.toml": parse_pyproject_toml,
        "setup.cfg": parse_setup_cfg,
        "setup.py": parse_setup_py,
    }
    log.debug(f"retrieving source for package {package_name}=={version}")
    try:
        source_path = get_package_source(package_name, version, pip_session=pip_session)
    except NoSDistError:
        log.warning(
            f"No source distribution found for {package_name}=={version}, "
            "skipping (build requirements may be incomplete)"
        )
        return []
    build_dependencies = []
    with tarfile.open(fileobj=source_path.open("rb")) as tarball:
        for file_name, parser in file_parser_map.items():
            root_dir = tarball.getnames()[0].split("/")[0]
            try:
                file = tarball.extractfile(f"{root_dir}/{file_name}")
            except KeyError:
                log.debug(
                    f"{file_name} file not found for package {package_name}=={version}",
                )
                continue
            log.debug(
                f"parsing file {file_name} for package {package_name}=={version}",
            )
            # utf-8-sig is required due to a very odd edge case I found with
            # package msal==1.24.1: it had a non printable character U+FEFF, which
            # was causing a SyntaxError when using ast to parse this setup.py.
            # utf-8-sig is a variant of UTF-8 invented by microsoft, so it kinda
            # makes sense this package had this encoding (msal is from microsoft).
            # No regression was found after running this with a large number of python
            # packages, so making this exception apply to all packages seem to be fine.
            file_contents = file.read().decode("utf-8-sig")
            try:
                build_dependencies += parser(file_contents)
            except SetupPyParsingError:
                error_msg = (
                    f"Unable to parse setup.py for package {package_name}=={version}."
                )
                if not raise_setuppy_parsing_exc:
                    log.error(error_msg)
                log.debug("{:=^80}".format(" setup.py contents "))
                log.debug(file_contents)
                log.debug("=" * 80)
                if raise_setuppy_parsing_exc:
                    raise SetupPyParsingError(error_msg)  # noqa: B904
    log.debug(f"found build dependencies: {build_dependencies}")
    return build_dependencies
