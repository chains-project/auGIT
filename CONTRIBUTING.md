# Contributing to auGIT

Thank you for your interest in contributing.

## Development setup

```bash
uv sync --all-groups
```

## Running tests

```bash
uv run --all-groups python -m pytest
```

Coverage must stay at or above 80% (`--cov-fail-under=80` in `pyproject.toml`).

## Linting

```bash
uv run ruff check src tests
```

## Testing philosophy

Write tests from an outside-in, specification-style perspective:

- Name tests after observable outcomes (e.g. `test_new_release_author_is_role_change_not_onboarding`).
- Assert on findings, database state, exported JSONL, or HTML content — not internal field names or CLI stdout formatting.
- Prefer `tmp_path` with a real SQLite database over mocking the store or report builder.
- Mock only at network or subprocess boundaries (GitHub API, PyPI/Maven HTTP, `git ls-remote`).

Shared fixtures live in `tests/conftest.py`.

## Pull requests

1. Keep changes focused on a single concern.
2. Add or update tests for behavior changes.
3. Ensure `ruff check` and `pytest` pass locally before opening a PR.
4. Update `CHANGELOG.md` for user-visible changes.

## Questions

Open a GitHub issue for bugs, feature requests, or design discussion.
