from datetime import UTC, datetime

from augit.analysis.report_builder import ReportOptions, build_trust_report
from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import EventIn
from augit.store import EventStore


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def test_acknowledge_saves_checkpoint(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    repo = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo,
                category="contributor",
                event_type="github_pull_request",
                source="github_api",
                source_event_id="pr:1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={
                    "number": 1,
                    "author_login": "alice",
                    "merged_at": "2026-01-01T12:00:00+00:00",
                    "state": "closed",
                },
            ),
        ],
    )
    store.finish_run(run_id)

    report = build_trust_report(
        store, repo, options=ReportOptions(acknowledge=True, as_of=_now())
    )
    assert report.status in ("ok", "findings")

    state = store.get_audit_state(repo)
    assert state is not None
    assert state.checkpoint_at is not None
    assert state.profile_json is not None


def test_reaudit_uses_stored_profile(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    repo = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo,
                category="contributor",
                event_type="github_pull_request",
                source="github_api",
                source_event_id="pr:1",
                source_timestamp=t0,
                observed_at=t0,
                payload={
                    "number": 1,
                    "author_login": "alice",
                    "merged_at": t0.isoformat().replace("+00:00", "Z"),
                    "state": "closed",
                    "review_comment_count": 5,
                    "review_count": 2,
                },
            ),
            EventIn(
                repo=repo,
                category="contributor",
                event_type="github_pull_request",
                source="github_api",
                source_event_id="pr:2",
                source_timestamp=t1,
                observed_at=t1,
                payload={
                    "number": 2,
                    "author_login": "bob",
                    "merged_at": t1.isoformat().replace("+00:00", "Z"),
                    "state": "closed",
                    "review_comment_count": 0,
                    "review_count": 0,
                },
            ),
        ],
    )
    store.finish_run(run_id)

    build_trust_report(
        store,
        repo,
        options=ReportOptions(acknowledge=True, as_of=t0),
    )
    report = build_trust_report(
        store,
        repo,
        options=ReportOptions(mode="reaudit", as_of=t1),
    )
    assert report.audit_mode == "reaudit"
    assert report.checkpoint_at is not None
