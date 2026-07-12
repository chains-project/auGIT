import json
from datetime import UTC, datetime

from augit.db import DbConfig, connect
from augit.export import export_events_jsonl
from augit.integrity import compare_refetch_views
from augit.migrate import migrate
from augit.models import IntegrityRefetchView, RepoKey
from augit.store import EventStore


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def test_integrity_compare_tag_retarget_and_missing_commit(tmp_path):
    repo = RepoKey(canonical_url="https://example.com/org/repo3", provider="github")

    prior = IntegrityRefetchView(
        branch_reachability={"main": ["aaa", "bbb"]},
        tag_targets={"v1.0.0": "bbb"},
        pull_requests=[{"pr_number": 1}],
        releases=[{"release_id": 10}],
        repo_identity={"canonical_url": repo.canonical_url, "provider": repo.provider},
    )
    new = IntegrityRefetchView(
        branch_reachability={"main": ["aaa"]},
        tag_targets={"v1.0.0": "aaa"},
        pull_requests=[{"pr_number": 1}],
        releases=[{"release_id": 10}],
        repo_identity={"canonical_url": repo.canonical_url, "provider": repo.provider},
    )

    events = compare_refetch_views(
        repo,
        prior,
        new,
        prior_observed_at=_now(),
        refetched_at=_now(),
    )

    subtypes = {e.payload["subtype"] for e in events}
    assert "commit_missing" in subtypes
    assert "tag_retargeted" in subtypes
    assert all(e.event_type == "integrity_drift" for e in events)


def test_jsonl_export_includes_schema_version(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo = RepoKey(canonical_url="https://example.com/org/repo4", provider="github")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")

    view = IntegrityRefetchView(tag_targets={"v1": "abc"})
    events = compare_refetch_views(
        repo, None, view, prior_observed_at=None, refetched_at=_now()
    )
    store.append_events(run_id, events)
    store.finish_run(run_id)

    out = tmp_path / "events.jsonl"
    count = export_events_jsonl(store, repo, out)
    assert count >= 1

    first = json.loads(out.read_text("utf-8").splitlines()[0])
    from augit.constants import SCHEMA_VERSION

    assert first["schema_version"] == SCHEMA_VERSION
    assert first["repo"]["canonical_url"] == repo.canonical_url
