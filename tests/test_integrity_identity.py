from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.integrity_identity import normalize_repo_identity
from augit.integrity_run import execute_integrity_refetch
from augit.migrate import migrate
from augit.models import EventIn, IntegrityRefetchView
from augit.store import EventStore
from augit.util import utc_now


def test_normalize_repo_identity_derives_full_name_from_url():
    repo_key = github_repo_key("chains-project/maven-lockfile")
    a = normalize_repo_identity({}, repo_key=repo_key)
    b = normalize_repo_identity(
        {
            "canonical_url": repo_key.canonical_url,
            "owner_login": "chains-project",
            "default_branch": "main",
        }
    )
    assert a == b


def test_first_check_skips_without_recorded_subjects(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/fresh")
    refetched_view = IntegrityRefetchView(
        branch_reachability={"main": ["sha1"]},
        tag_targets={"v1": "sha1"},
        pull_requests=[{"pr_number": 1}],
        releases=[{"release_id": 9}],
        repo_identity=normalize_repo_identity({}, repo_key=repo_key),
    )

    result = execute_integrity_refetch(
        store, repo_key, refetched_view, refetched_at=utc_now()
    )

    assert result.integrity_events == []
    assert result.summary.get("skipped") == "no_recorded_subjects"


def test_execute_integrity_refetch_is_idempotent(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/idempotent")
    repo_id = store.ensure_repo(repo_key)
    run_id = store.start_run(repo_id, mode="incremental")
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_tag_target",
                source="git",
                source_event_id="t1",
                source_timestamp=utc_now(),
                observed_at=utc_now(),
                payload={"tag": "v1", "sha": "old_sha"},
            ),
        ],
    )
    store.finish_run(run_id)

    refetched_view = IntegrityRefetchView(
        branch_reachability={},
        tag_targets={"v1": "new_sha"},
        pull_requests=[],
        releases=[],
        repo_identity=normalize_repo_identity({}, repo_key=repo_key),
    )

    first = execute_integrity_refetch(
        store, repo_key, refetched_view, refetched_at=utc_now()
    )
    second = execute_integrity_refetch(
        store, repo_key, refetched_view, refetched_at=utc_now()
    )

    assert any(e.payload["subtype"] == "tag_retargeted" for e in first.integrity_events)
    assert second.integrity_events == []
