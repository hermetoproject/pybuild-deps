# Usage

```{eval-rst}
.. click:: pybuild_deps.__main__:cli
    :prog: pybuild-deps
    :nested: full
```

## Package indexes

`pybuild-deps compile` resolves build dependencies with [uv]. Index options in
the requirements file (`--index-url`, `--extra-index-url`, `--find-links` and
so on) are used for resolution and recorded in the output. uv's default
`first-index` strategy can choose a different version than pip when the same
package is available from multiple indexes. See [uv's index strategy docs].

pip configuration files (`pip.conf`) are not read. The common pip index
environment variables `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, and
`PIP_FIND_LINKS` are mapped to their uv equivalents; set the `UV_*` variables
directly when both forms are present. `PIP_FIND_LINKS` uses spaces between
locations; pybuild-deps converts it to uv's comma-separated `UV_FIND_LINKS`
form. A true `PIP_NO_INDEX` value is passed to uv as `--no-index`. Environment
variables affect resolution only; only options from input requirements files
are copied to the generated output. uv
configuration files (`uv.toml`, `[tool.uv]`) are ignored, so the result
doesn't depend on the directory pybuild-deps runs from.

Source archives for named packages are downloaded from PyPI by default. Remote
direct URLs and pinned VCS requirements are also supported.

[uv]: https://docs.astral.sh/uv/
[uv's index strategy docs]: https://docs.astral.sh/uv/concepts/indexes/#searching-across-multiple-indexes
