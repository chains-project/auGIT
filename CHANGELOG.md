# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-24

### Added

- Append-only SQLite audit log for GitHub, PyPI, and Maven supply-chain signals
- Incremental collectors: PRs (GraphQL), commits, releases, tags, dependency manifests, git refs
- Trust report with extensible metrics (onboarding, role changes, irregular commits, and more)
- Optional integrity check (live refetch vs recorded audit trail)
- Package linking (PyPI/Maven → GitHub)
- JSONL export
- Benchmark evaluation script (`eval-benchmarks.sh`)
