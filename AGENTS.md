# pybuild-deps

Given a fully resolved requirements file, pybuild-deps
resolves and pins PEP-517 build dependencies. It never
resolves runtime dependencies itself.

If unsure about pybuild-deps conventions, read the relevant
files or ask. Do not assume.

## Principles

1. **Build-dep accuracy** -- only report what is declared in
   pyproject.toml, setup.cfg, or setup.py. Do not invent
   or infer undeclared dependencies.
2. **No arbitrary code execution** -- setup.py is parsed via
   AST, never exec'd. The AST parser intentionally rejects
   unconventional patterns.
3. **pip internals are fragile** -- the codebase uses
   `pip._internal` and pip-tools internals extensively.
   These APIs break between releases. Test against the
   pinned pip (bundled submodule) and pip-tools versions
   before changing anything that touches them.

## Project Structure

- `src/pybuild_deps/` source code (src layout)
- `src/pybuild_deps/modules/pip` vendored pip git submodule,
  never edit it and exclude it from code searches
- `tests/` unit and e2e tests
- `docs/` user-facing documentation
- [pyproject.toml](pyproject.toml) project metadata, all
  tool settings, minimum Python version

## Git Workflow

- DCO sign-off and AI trailer required:
  `git commit -s --trailer "Assisted-by: <AI tool name>"`
- Rebase only, no merge commits
- Every commit must pass `pytest -m "not e2e"` and
  `nox -s pre-commit` independently
- Changes split into standalone commits, not a single blob
- Commit messages explain WHY, not what
- Commit messages must reference issues and PRs with full
  URLs (e.g.,
  `https://github.com/hermetoproject/pybuild-deps/issues/42`),
  never short references like `#42`
- No gitmojis

## Environment

- uv and Nox must be available as CLI tools. See
  [CONTRIBUTING.md](CONTRIBUTING.md) for setup, including
  the pip submodule checkout
- Install project deps: `uv sync`
- CI tests Python 3.10-3.13

## Commands

    pytest -m "not e2e"        # unit tests (single Python)
    nox -s pre-commit          # linting and formatting
    nox -s tests               # unit tests (all 4 Python
                               # versions, slow)
    nox -s e2e-tests           # e2e tests (network access)

Use `pytest` directly for fast iteration. Use `nox -s tests`
for final verification only.

## Code Style

- Google-style docstrings (enforced by pydoclint)
- Comments explain WHY, never repeat HOW the code works
- `nox -s pre-commit` handles formatting and linting
- Always preserve trailing newlines at end of files

## Testing

- `conftest.py` lives at the repo root, not in `tests/`
- Tests that need network access must be marked
  `@pytest.mark.e2e`
- Add new test cases instead of modifying existing ones
- Test pybuild-deps logic, not stdlib or library behavior
- If changes add functionality, update `docs/` accordingly

If you encounter what appears to be a potential security
vulnerability, do not fix it or include it in a commit. Stop
and alert the human operator.
