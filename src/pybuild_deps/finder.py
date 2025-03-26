"""Find build dependencies of a python package."""

from __future__ import annotations

import operator
import re
import tarfile
from types import FunctionType

import requests
from pip._internal.network.session import PipSession

from .logger import log
from .parsers import parse_pyproject_toml, parse_setup_cfg, parse_setup_py
from .parsers.setup_py import SetupPyParsingError
from .source import get_package_source


a = (
    operator.add
)  # The autolinter is too smart, it would delete oeprators import otherwise
# It also messes up code layout


# NOTE: this is exactly what is said on the label, a _persistent_ cache.
# @persistent_cache("find-build-deps", ignore_kwargs=["pip_session"])
def find_build_dependencies(
    package_name,
    version,
    raise_setuppy_parsing_exc=True,
    pip_session: PipSession | None = None,
    seen: set | None = None,
) -> list[str]:
    """Find build dependencies for a given package."""
    file_parser_map = {
        "pyproject.toml": parse_pyproject_toml,
        "setup.cfg": parse_setup_cfg,
        "setup.py": parse_setup_py,
    }
    log.debug(f"retrieving source for package {package_name}=={version}")
    source_path = get_package_source(package_name, version, pip_session=pip_session)
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

    # NOTE: this does not prevent one package from appearing mutiple times.
    # However, pip-compile deals with this.
    seen = set() if seen is None else seen
    for dep_line in build_dependencies:
        package_name, package_versions = extract_depname_and_versions(dep_line)
        if package_name in seen:
            continue
        seen.add(package_name)
        best_version = package_versions[-1]
        build_dependencies += find_build_dependencies(
            package_name, best_version, seen=seen
        )

    return build_dependencies


# Splitting on dep_condition_re would result in either:
#  ["", left|None, right|None, tail]
# or just in ["non-matching-string"].
# Note, that either left or right would be present. First element could be
# safely dropped since this will be the head of the string until first match
# (which in this case will be either "" or " " The same regexp could be used to
# split the original line.  In that case we'd need the first element too.
dep_condition_re = re.compile(
    r"""(===)
       |([!<>=~]=)
       |([<>])
    """,
    re.VERBOSE,
)


def one_which_is_not_None(_tuple):
    # Impossible scenarios first
    if all(x is None for x in _tuple):
        raise ValueError("All values are None")
    elif len(_tuple) - _tuple.count(None) > 1:
        raise ValueError(f"Multiple values: {_tuple}")
    # Normal scenarios
    else:
        return next(x for x in _tuple if x is not None)


def expand_operators(op, val):
    # Need to do this because of ~= which does not directly translate
    # into corresponding operator.
    # ~= 2.2.0 is equivalent to >=2.2.0 == 2.2.*
    # === is, on the other hand, a direct comparison, but has to be translated
    # into one
    # >, <, >= and != could be used as is.
    if op == "~=":
        return (">=", val, "==", val[:-1] + "*")
    return op, val


def straigtened(lst):
    # special case for rewriting
    out = []
    for el in lst:
        if len(el) == 2:
            out.append(el)
        elif len(el) == 4:
            out.append(tuple(el[:2]))
            out.append(tuple(el[2:]))
        else:
            raise ValueError(f"Impossible expansion: {el}")
    return out


def fuzzy_eq(op, val):
    # 2.* -> re.compile("2\..*")
    prefix, star, nothing = op.partition("*")
    prefix = prefix.replace(".", "\\.")
    a_re = (prefix + ".*") if star else prefix
    return re.match(a_re, val) is not None


def fuzzy_neq(op, val):
    return not fuzzy_eq(op, val)


def translate_operators(op, val):
    # Equality and inequality could rely on glob stars, so they have to be
    # translated into a regexp.
    operators_map = {
        ">": f"operator.gt({{}}, '{val}')",
        "<": f"operator.lt({{}}, '{val}')",
        ">=": f"operator.ge({{}}, '{val}')",
        "<=": f"operator.le({{}}, '{val}')",
        "===": f"operator.eq({{}}, '{val}')",
        "==": f"fuzzy_eq('{val}', {{}})",
        "!=": f"fuzzy_neq('{val}', {{}})",
    }
    return operators_map[op]


def convert_conditions_to_filter(conditions):
    """Construct a filtering function"""
    if not conditions:
        return lambda x: True
    # At this point conditions will always be of shape `foo<dep_condition_re>version`
    split_conditions = [dep_condition_re.split(c)[1:] for c in conditions.split(",")]
    # The above is a list of 4-tuples: ("", Optional[operator], Optional[operator], version)
    pruned_conditions = [
        (one_which_is_not_None(c[:3]), c[-1]) for c in split_conditions
    ]
    expanded_conditions = straigtened(
        expand_operators(op, val) for op, val in pruned_conditions
    )
    translated_conditions = [
        translate_operators(op, val) for op, val in expanded_conditions
    ]
    spliced_conditions = [fn.format("x") for fn in translated_conditions]
    filter_function_code = "lambda x: " + " and ".join(spliced_conditions)

    filter_function = FunctionType(
        compile(filter_function_code, "cctf", "exec").co_consts[0], globals()
    )
    return filter_function


# TODO: add a link to PEP
def extract_depname_and_versions(dep_line):
    """Extract dependency name and acceptable versions from a dependency line.

    Dep_line is a string of the following format:
        foo>=1.0,<2
        bar==2.3.4
        baz!=3.1.2
        meep>2.3.4,!=3.1.2
        quux==3.1.2; python<=3.11
    """
    # Ignore extra conditions for a package, pip-compile will deal with it later
    split = dep_condition_re.split(dep_line.partition(";")[0])
    package_name, conditions = split[0], "".join(c for c in split[1:] if c is not None)
    satisfies_conditions = convert_conditions_to_filter(conditions)

    r = requests.get(f"https://pypi.org/pypi/{package_name}/json/")
    version_candidates = [
        vc for vc in r.json()["releases"].keys() if satisfies_conditions(vc)
    ]

    return package_name, version_candidates
