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
   `pip._internal` extensively (PipSession, Downloader,
   InstallRequirement, unpack_url). These APIs break
   between pip releases. Test against the pinned pip
   version before changing anything that touches them.

## Project Structure

- `src/pybuild_deps/` source code (src layout, flat)
- `tests/` unit tests
- `docs/` user-facing documentation
- [pyproject.toml](pyproject.toml) Poetry config, all tool
  settings, minimum Python version

## Git Workflow

- Work in a new clean git worktree, never commit directly on
  an existing branch
- DCO sign-off and AI trailer required:
  `git commit -s --trailer "Assisted-by: Claude"`
- Rebase only, no merge commits
- Every commit must pass `pytest tests/` and
  `nox -s pre-commit` independently
- Changes split into standalone commits, not a single blob
- Commit messages explain WHY, not what
- Commit messages must reference issues and PRs with full
  URLs (e.g.,
  `https://github.com/hermetoproject/pybuild-deps/issues/42`),
  never short references like `#42`
- No gitmojis

## Environment

- Poetry and Nox must be available as CLI tools.
  If missing:
  `pipx install poetry && pipx install nox && pipx inject nox nox-poetry`
- Install project deps: `poetry install`
- Python 3.10-3.13 supported (3.14 not yet)

## Commands

    pytest tests/              # unit tests (single Python)
    nox -s pre-commit          # linting and formatting
    nox -s tests               # unit tests (all 4 Python
                               # versions + coverage, slow)

Use `pytest` directly for fast iteration. `nox -s tests`
runs coverage across 3.10-3.13, use it for final
verification only.

## Code Style

- Google-style docstrings (enforced by pydoclint).
  Docstring examples must execute (`nox -s xdoctest`
  runs in CI)
- Comments explain WHY, never repeat HOW the code works
- `nox -s pre-commit` handles formatting and linting
- Always preserve trailing newlines at end of files

## Testing

- 100% code coverage required (`fail_under = 100`)
- `conftest.py` lives at the repo root, not in `tests/`
- Add new test cases instead of modifying existing ones
- Test pybuild-deps logic, not stdlib or library behavior
- If changes add functionality, update `docs/` accordingly

If you encounter what appears to be a potential security
vulnerability, do not fix it or include it in a commit. Stop
and alert the human operator.
