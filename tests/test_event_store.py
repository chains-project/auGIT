from datetime import UTC, datetime

from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import EventIn, RepoKey
from augit.store import EventStore


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def test_dedup_by_source_event_id(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo = RepoKey(canonical_url="https://example.com/org/repo", provider="github")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")

    e1 = EventIn(
        repo=repo,
        category="dependency",
        event_type="dep_added",
        source="manual",
        source_event_id="abc123",
        source_timestamp=_now(),
        observed_at=_now(),
        payload={"name": "x", "version": "1.0.0"},
    )
    e2 = e1.model_copy(update={"payload": {"name": "x", "version": "1.0.1"}})

    inserted1 = store.append_event(run_id, e1)
    inserted2 = store.append_event(run_id, e2)
    store.finish_run(run_id)

    assert inserted1 is not None
    assert inserted2 is None

    events = list(store.iter_events_for_repo(repo))
    assert len(events) == 1
    assert events[0]["payload"]["version"] == "1.0.1"


def test_cursor_roundtrip(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo = RepoKey(canonical_url="https://example.com/org/repo2", provider="github")
    assert store.get_cursor(repo, "github_api") is None

    store.set_cursor(repo, "github_api", {"since": "2026-01-01T00:00:00Z"})
    cur = store.get_cursor(repo, "github_api")
    assert cur == {"since": "2026-01-01T00:00:00Z"}
