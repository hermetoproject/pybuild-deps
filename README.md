# pybuild-deps

[![PyPI](https://img.shields.io/pypi/v/pybuild-deps.svg)][pypi status]
[![Status](https://img.shields.io/pypi/status/pybuild-deps.svg)][pypi status]
[![Python Version](https://img.shields.io/pypi/pyversions/pybuild-deps)][pypi status]
[![License](https://img.shields.io/pypi/l/pybuild-deps)][license]

[![Read the documentation at https://pybuild-deps.readthedocs.io/](https://img.shields.io/readthedocs/pybuild-deps/latest.svg?label=Read%20the%20Docs)][read the docs]
[![Tests](https://github.com/hermetoproject/pybuild-deps/workflows/Tests/badge.svg)][tests]
[![Codecov](https://codecov.io/gh/hermetoproject/pybuild-deps/branch/main/graph/badge.svg)][codecov]

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)][pre-commit]
[![Ruff codestyle][ruff badge]][ruff project]

[pypi status]: https://pypi.org/project/pybuild-deps/
[read the docs]: https://pybuild-deps.readthedocs.io/
[tests]: https://github.com/hermetoproject/pybuild-deps/actions?workflow=Tests
[codecov]: https://app.codecov.io/gh/hermetoproject/pybuild-deps
[pre-commit]: https://github.com/pre-commit/pre-commit
[ruff badge]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
[ruff project]: https://github.com/charliermarsh/ruff

CLI tools to help dealing with python build dependencies. It aims to complement
tools that can pin dependencies like `pip-tools` and `poetry`.
For users relying exclusively on python wheels, those tools are more than enough.
However, for users building applications from source, finding and pinning build dependencies
is required for reproducible builds.

`pybuild-deps` might be useful for developers that need to explicitly declare
**all** dependencies for compliance reasons or supply chain concerns.

## Features

- find build dependencies for a given python package
- generate pinned build requirements from requirements.txt files.

## Installation

You can install _pybuild-deps_ via [pip] from [PyPI]:

```console
$ pip install pybuild-deps
```

## Usage

Please see the [Command-line Reference] for details.

## Contributing

Contributions are very welcome.
To learn more, see the [Contributor Guide].

## License

Distributed under the terms of the [GPL 3.0 license][license],
_PyBuild Deps_ is free and open source software.

## Issues

If you encounter any problems,
please [file an issue] along with a detailed description.

## Credits

This project was generated from [@cjolowicz]'s [Hypermodern Python Cookiecutter] template.

[@cjolowicz]: https://github.com/cjolowicz
[pypi]: https://pypi.org/
[hypermodern python cookiecutter]: https://github.com/cjolowicz/cookiecutter-hypermodern-python
[file an issue]: https://github.com/hermetoproject/pybuild-deps/issues
[pip]: https://pip.pypa.io/

<!-- github-only -->

[license]: https://github.com/hermetoproject/pybuild-deps/blob/main/LICENSE
[contributor guide]: https://github.com/hermetoproject/pybuild-deps/blob/main/CONTRIBUTING.md
[command-line reference]: https://pybuild-deps.readthedocs.io/en/latest/usage.html
