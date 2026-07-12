from augit.collectors.github_api import github_repo_key
from augit.collectors.github_prs import pr_to_event
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.store import EventStore


def test_second_run_does_not_duplicate_events(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo_key)

    pr = {
        "number": 1,
        "state": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"sha": "abc", "repo": {"full_name": "org/repo"}},
    }

    # Run 1: insert event
    run1 = store.start_run(repo_id, mode="incremental")
    inserted1 = store.append_event(run1, pr_to_event(repo_key, "org/repo", pr))
    store.finish_run(run1)
    assert inserted1 is not None

    # Run 2: attempt to insert same provider-id again -> should be ignored
    run2 = store.start_run(repo_id, mode="incremental")
    inserted2 = store.append_event(run2, pr_to_event(repo_key, "org/repo", pr))
    store.finish_run(run2)
    assert inserted2 is None

    all_events = list(store.iter_events_for_repo(repo_key))
    assert len(all_events) == 1


def test_second_run_updates_pr_when_payload_changes(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo_key)

    open_pr = {
        "number": 1,
        "state": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"sha": "abc", "repo": {"full_name": "org/repo"}},
    }
    merged_pr = {
        **open_pr,
        "state": "closed",
        "merged_at": "2026-01-03T00:00:00Z",
        "merge_commit_sha": "deadbeef",
    }

    run1 = store.start_run(repo_id, mode="incremental")
    assert (
        store.append_event(run1, pr_to_event(repo_key, "org/repo", open_pr)) is not None
    )
    store.finish_run(run1)

    run2 = store.start_run(repo_id, mode="incremental")
    assert (
        store.append_event(run2, pr_to_event(repo_key, "org/repo", merged_pr)) is None
    )
    store.finish_run(run2)

    events = list(store.iter_events_for_repo(repo_key))
    assert len(events) == 1
    assert events[0]["payload"]["merged_at"] == "2026-01-03T00:00:00Z"
