# augit

Append-only audit log for supply-chain signals from GitHub, PyPI, and Maven Central.

auGIT collects incremental events from package registries and GitHub repositories, stores them in a signed append-only SQLite log, and produces HTML trust reports with extensible governance metrics. See [framework.txt](framework.txt) for the design rationale and threat model.

## Setup

```bash
uv sync --all-groups
export GITHUB_TOKEN=ghp_...   # required for GitHub collect; also for check (integrity refetch)
export SSC_AUDIT_DB=./audit.db   # optional; avoids passing --db on every command
```

A classic personal access token or fine-grained token with **read** access to repository metadata is sufficient for collection.

## Quick start (GitHub repository)

```bash
# Create database
augit db init --path ./audit.db

# Collect incremental events (PRs, commits, releases, tags, dependency diffs)
augit --db ./audit.db collect github owner/repo --sources all

# Trust report (HTML) from the audit log — default path
augit --db ./audit.db report owner/repo --out report.html

# Optional: integrity check (live refetch vs recorded audit trail). Run only when you need
# history-drift checks; not required for routine dependency updates.
# augit --db ./audit.db check owner/repo

# Export JSONL for analysis
augit --db ./audit.db export owner/repo --out events.jsonl
```

With `SSC_AUDIT_DB` set:

```bash
augit db init --path ./audit.db
export SSC_AUDIT_DB=./audit.db
augit collect github owner/repo
augit report owner/repo --out report.html
# augit check owner/repo   # optional
augit export owner/repo --out events.jsonl
```

## Commands

| Command | Description |
|---------|-------------|
| `db init --path PATH` | Initialize SQLite schema |
| `collect github REPO [--sources all\|prs,commits,...]` | Incremental GitHub collection |
| `collect pypi NAME` | PyPI version events (+ auto GitHub link) |
| `collect maven GAV` | Maven version events (+ auto GitHub link) |
| `report REPO --out FILE` | HTML trust report from audit log |
| `check REPO` | Optional integrity check: compare recorded audit trail vs live refetch |
| `link pypi NAME` / `link maven GAV` | Resolve package → GitHub URL |
| `link show --provider pypi\|maven PACKAGE` | Show stored package link |
| `export REPO --out FILE` | Export events as JSONL |

Global option: `--db PATH` (or `SSC_AUDIT_DB`).

### Report options

| Flag | Default | Purpose |
|------|---------|---------|
| `--mode initial\|reaudit` | `initial` | Initial audit learns profile from pre-tail history; re-audit uses last checkpoint |
| `--tail-days N` | `90` | Compare-window length for initial audits |
| `--as-of ISO-DATE` | latest event / now | Fixed end of compare window (retrospective audits) |
| `--acknowledge` | off | Store checkpoint and profile snapshot after report |

**Initial audit workflow:** `collect` → `report` (profile learned from history before the 90-day tail).

**Re-audit workflow:** `collect` → `report --mode reaudit` (compares post-checkpoint activity to stored profile).

**Advance checkpoint:** `report --acknowledge` after accepting the report.

**Retrospective analysis:** `report --as-of 2018-10-01T00:00:00Z` fixes the compare window end for incident-aligned evaluation.

### Check

Compares the **recorded audit trail** (from `collect`) against a **live refetch** of the same subjects (GitHub API + `git ls-remote` for branch tips and tag targets). Drift events are appended to the log and surfaced in `report`.

**Default flow:** `collect` → `report` (fast; governance signals from API metadata).

**When you need history integrity:** run `collect github` (includes `git_refs`) then `check`, then `report`.

### Check flags

- `--no-git`: GitHub API only (skip `git ls-remote`)
- `--git-only`: `git ls-remote` only (no GitHub API)
- `--git-remote URL`: override remote URL (default: `https://github.com/owner/repo.git`)
- `--branch NAME`: limit git ref collection to specific branches (repeatable)

### Collect sources

`--sources all` includes: `prs`, `commits`, `releases`, `tags`, `dependencies`, `git_refs`.

**Pull requests** are collected via the **GitHub GraphQL API** (batched metadata including review counts). This requires a valid `GITHUB_TOKEN` with repository read access. Commits, releases, tags, and dependencies still use the REST API.

The `dependencies` source parses manifest diffs on recently merged PRs (`package.json`, `requirements.txt`, `pom.xml`, etc.) and appends `dependency_manifest_change` events.

## PyPI → GitHub workflow

```bash
augit collect pypi requests
augit link show --provider pypi requests
augit collect github psf/requests --sources all
augit report psf/requests --out report.html
```

## Resetting the database

`db init` only creates or migrates schema; it does not wipe data. To start fresh:

```bash
rm -f audit.db audit.db-wal audit.db-shm
augit db init --path ./audit.db
```

This clears events, cursors, integrity snapshots, package links, and checkpoints. Re-run `collect` and `report` afterward; run `check` only if needed.

## Evaluation / benchmarks

[`eval-benchmarks.sh`](eval-benchmarks.sh) runs retrospective audits against known supply-chain incidents and negative controls. It requires `GITHUB_TOKEN` and generates HTML reports for manual review.

```bash
export GITHUB_TOKEN=ghp_...
./eval-benchmarks.sh init
./eval-benchmarks.sh positives    # incident cases
./eval-benchmarks.sh negatives    # control cases
./eval-benchmarks.sh all
```

Reports are written to `./eval-reports/` by default. Override paths with `EVAL_DB` and `EVAL_OUT`.

## Development

```bash
uv sync --all-groups
uv run augit --help
uv run ruff check src tests
uv run --all-groups python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for testing philosophy and PR guidelines.

## License

MIT — see [LICENSE](LICENSE).

## Analysis modules

| Module | Role |
|--------|------|
| `analysis/profile.py` | Repository profile and audit context (initial / re-audit) |
| `analysis/timeline.py` | Parse audit-log rows into structured events |
| `analysis/trust_signals/` | Extensible metric base + runner (one class per in-scope signal) |
| `analysis/report_builder.py` | Orchestrate profile, detection, checkpoint persistence |
