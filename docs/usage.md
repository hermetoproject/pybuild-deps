# Usage

`pybuild-deps list` reports the build dependencies declared by each package
in a fully resolved requirements file:

```console
$ pybuild-deps list requirements.txt
```

It reads `[build-system].requires` from `pyproject.toml` and `setup_requires`
from `setup.cfg` and supported `setup.py` patterns. Requirement specifiers,
extras, and build dependency environment markers are preserved as declared.
No versions are selected, and discovered build dependencies are not recursively
inspected. Use `compile` to resolve and pin the recursive build dependencies.
Static inspection cannot discover additional requirements supplied by build
backend hooks or unsupported dynamic setup logic; `setup.py` is never executed.

With illustrative input packages, the text report looks like:

```text
example-a==1.0:
  setuptools>=64
  wheel

example-b==2.0:
  (no declared build dependencies found)
```

Specify several input files to inspect their combined requirements, or omit
the paths to read `requirements.txt` in the current directory. Nested `-r`
includes are supported. Constraint-only entries from `-c` files are not
inspection targets. Duplicate input requirements are inspected once, and
packages are reported in input order.

Input validation and environment marker filtering follow `compile`: all input
requirements must be pinned or supported source URLs, including requirements
with inactive markers. Only packages whose input markers match the current
environment are inspected. Discovered build dependency markers are not filtered.

The report is written to stdout by default. Select JSON for automation or
write a report with `-o`:

```console
$ pybuild-deps list requirements.txt --format json -o build-deps.json
```

JSON maps each input requirement to its list of build dependency strings.
An empty list means no declarations were found by the static parsers. If a
package has no source distribution, its value is `null`, its text report says
`(source distribution unavailable)`, and a warning is written to stderr.
Other inspection or parsing errors stop the command with exit code 2; an
existing output file is left intact. An empty input produces `{}` in JSON or
no text output.

Named releases are inspected using source distributions from public PyPI,
as with `find-build-deps`; requirements-file index options do not change that
source lookup. Supported direct archive and VCS URLs can also be used.

```{eval-rst}
.. click:: pybuild_deps.__main__:cli
    :prog: pybuild-deps
    :nested: full
```
