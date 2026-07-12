import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_integrity_refetch import (
    build_integrity_refetch_view,
    fetch_github_api_subjects,
)
from augit.db import DbConfig, connect
from augit.integrity import compare_refetch_views
from augit.integrity_baseline import build_view_from_audit_log
from augit.integrity_identity import normalize_repo_identity
from augit.integrity_run import execute_integrity_refetch
from augit.migrate import migrate
from augit.models import EventIn, IntegrityRefetchView
from augit.store import EventStore


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def test_build_view_from_audit_log_reconstructs_tags(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo_key)
    run_id = store.start_run(repo_id, mode="incremental")
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo_key,
                category="contributor",
                event_type="github_tag",
                source="github_api",
                source_event_id="t1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={"tag_name": "v1.0.0", "sha": "bbb222"},
            ),
        ],
    )
    store.finish_run(run_id)

    view = build_view_from_audit_log(store, repo_key)
    assert view.tag_targets["v1.0.0"] == "bbb222"


def test_build_view_from_audit_log_reconstructs_git_refs(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo_key)
    run_id = store.start_run(repo_id, mode="incremental")
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_branch_tip",
                source="git",
                source_event_id="b1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={"branch": "main", "sha": "deadbeef"},
            ),
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_tag_target",
                source="git",
                source_event_id="t1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={"tag": "v1.0.0", "sha": "feedface"},
            ),
        ],
    )
    store.finish_run(run_id)

    view = build_view_from_audit_log(store, repo_key)
    assert view.branch_reachability["main"] == ["deadbeef"]
    assert view.tag_targets["v1.0.0"] == "feedface"


def test_compare_does_not_false_positive_repo_moved():
    repo_key = github_repo_key("chains-project/maven-lockfile")
    identity = normalize_repo_identity({}, repo_key=repo_key)
    recorded = IntegrityRefetchView(
        branch_reachability={"main": ["abc"]},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity=identity,
    )
    refetched = IntegrityRefetchView(
        branch_reachability={"main": ["abc"]},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity=identity,
    )

    events = compare_refetch_views(
        repo_key,
        recorded,
        refetched,
        prior_observed_at=None,
        refetched_at=_now(),
    )

    assert events == []


def test_repo_moved_when_canonical_url_changes():
    repo_key = github_repo_key("org/old-repo")
    recorded = IntegrityRefetchView(
        repo_identity=normalize_repo_identity(
            {"canonical_url": "https://github.com/org/old-repo"}, repo_key=repo_key
        ),
    )
    refetched = IntegrityRefetchView(
        repo_identity=normalize_repo_identity(
            {
                "canonical_url": "https://github.com/org/new-repo",
                "full_name": "org/new-repo",
            }
        ),
    )

    events = compare_refetch_views(
        repo_key,
        recorded,
        refetched,
        prior_observed_at=_now(),
        refetched_at=_now(),
    )

    assert any(e.payload["subtype"] == "repo_moved" for e in events)
    assert all(e.event_type == "integrity_drift" for e in events)


def test_compare_emits_branch_tip_drift():
    repo_key = github_repo_key("org/repo2")
    recorded = IntegrityRefetchView(
        branch_reachability={"main": ["gone_sha"]},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity={"canonical_url": repo_key.canonical_url},
    )
    refetched = IntegrityRefetchView(
        branch_reachability={"main": ["new_sha"]},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity={"canonical_url": repo_key.canonical_url},
    )

    events = compare_refetch_views(
        repo_key,
        recorded,
        refetched,
        prior_observed_at=None,
        refetched_at=_now(),
    )

    subtypes = {e.payload["subtype"] for e in events}
    assert "commit_missing" in subtypes
    assert "commit_added" in subtypes


def test_execute_integrity_refetch_detects_recorded_drift(tmp_path):
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    repo_key = github_repo_key("org/repo3")
    repo_id = store.ensure_repo(repo_key)
    run_id = store.start_run(repo_id, mode="incremental")
    store.append_events(
        run_id,
        [
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_branch_tip",
                source="git",
                source_event_id="b1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={"branch": "main", "sha": "only_in_log"},
            ),
        ],
    )
    store.finish_run(run_id)

    refetched_view = IntegrityRefetchView(
        branch_reachability={"main": []},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity={"canonical_url": repo_key.canonical_url},
    )

    result = execute_integrity_refetch(
        store, repo_key, refetched_view, refetched_at=_now()
    )

    subtypes = {e.payload["subtype"] for e in result.integrity_events}
    assert "commit_missing" in subtypes


def test_build_integrity_refetch_view_merges_git_and_api():
    repo_key = github_repo_key("org/repo4")

    api_subjects = {
        "pull_requests": [
            {"pr_number": 12, "merged_at": None, "merge_commit_sha": None}
        ],
        "releases": [
            {
                "release_id": 99,
                "tag_name": "v1",
                "published_at": None,
                "author": "alice",
            }
        ],
        "tag_targets": {"api-tag": "api_sha"},
        "repo_identity": {
            "canonical_url": "https://github.com/org/repo4",
            "full_name": "org/repo4",
        },
    }

    from augit.collectors.git_refs import CollectResult

    git_events = [
        EventIn(
            repo=repo_key,
            category="integrity",
            event_type="git_branch_tip",
            source="git",
            source_event_id="b1",
            payload={"branch": "main", "sha": "git_sha"},
        ),
        EventIn(
            repo=repo_key,
            category="integrity",
            event_type="git_tag_target",
            source="git",
            source_event_id="t1",
            payload={"tag": "git-tag", "sha": "git_sha"},
        ),
    ]

    client = MagicMock()
    with (
        patch(
            "augit.collectors.github_integrity_refetch.fetch_github_api_subjects",
            return_value=api_subjects,
        ),
        patch(
            "augit.collectors.github_integrity_refetch.collect_git_refs",
            return_value=CollectResult(events=git_events, cursor={}),
        ),
    ):
        view = build_integrity_refetch_view(client, repo_key, use_git=True)

    assert view.branch_reachability["main"] == ["git_sha"]
    assert view.tag_targets["git-tag"] == "git_sha"
    assert view.tag_targets["api-tag"] == "api_sha"
    assert view.pull_requests[0]["pr_number"] == 12
    assert view.releases[0]["release_id"] == 99


def test_fetch_github_api_subjects_parses_fixture_pages():
    fixture = Path(__file__).parent / "fixtures" / "github_prs_page1.json"
    pr_page = json.loads(fixture.read_text("utf-8"))
    releases_fixture = Path(__file__).parent / "fixtures" / "github_releases_page1.json"
    rel_page = json.loads(releases_fixture.read_text("utf-8"))
    tags_fixture = Path(__file__).parent / "fixtures" / "github_tags_page1.json"
    tag_page = json.loads(tags_fixture.read_text("utf-8"))

    client = MagicMock()
    client.paginate.side_effect = [iter([pr_page]), iter([rel_page]), iter([tag_page])]
    client.get_json.return_value = (
        {
            "html_url": "https://github.com/org/repo",
            "full_name": "org/repo",
            "owner": {"login": "org"},
            "default_branch": "main",
        },
        {},
    )

    out = fetch_github_api_subjects(
        client, "org/repo", max_pages_prs=1, max_pages_releases=1, max_pages_tags=1
    )
    assert out["pull_requests"][0]["pr_number"] == 12
    assert out["releases"][0]["release_id"] == 99
    assert "v1.0.0" in out["tag_targets"]
