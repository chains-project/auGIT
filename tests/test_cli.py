import json
from datetime import UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from augit.cli import app
from augit.cli.context import ENV_DB
from augit.collectors.github_api import github_repo_key
from augit.models import IntegrityRefetchView, RepoKey

runner = CliRunner()


def _graphql_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text("utf-8"))


def test_db_init_without_global_db(tmp_path):
    db_path = tmp_path / "audit.db"
    result = runner.invoke(app, ["db", "init", "--path", str(db_path)])
    assert result.exit_code == 0
    assert db_path.exists()


def test_collect_github_requires_db(monkeypatch):
    monkeypatch.delenv(ENV_DB, raising=False)
    result = runner.invoke(app, ["collect", "github", "org/repo"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "--db" in combined or ENV_DB in combined


def test_collect_github_persists_pr_events(tmp_path):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture

    with patch(
        "augit.cli.collect.GitHubClient.from_env",
        return_value=client,
    ):
        result = runner.invoke(
            app,
            ["--db", str(db_path), "collect", "github", "org/repo", "--sources", "prs"],
        )

    assert result.exit_code == 0
    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    repo_key = github_repo_key("org/repo")
    events = list(store.iter_events_for_repo(repo_key))
    conn.close()
    assert len(events) == 2
    assert all(e["event_type"] == "github_pull_request" for e in events)


def test_check_with_db_mocked(tmp_path):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    empty_view = IntegrityRefetchView(
        branch_reachability={},
        tag_targets={},
        pull_requests=[],
        releases=[],
        repo_identity={},
    )
    mock_run = MagicMock(
        integrity_events=[],
        run_id=99,
        summary={"integrity_events_emitted": 0},
    )

    with (
        patch(
            "augit.cli.check.GitHubClient.from_env",
            return_value=MagicMock(),
        ),
        patch(
            "augit.cli.check.build_integrity_refetch_view",
            return_value=empty_view,
        ),
        patch(
            "augit.cli.check.execute_integrity_refetch",
            return_value=mock_run,
        ),
    ):
        result = runner.invoke(
            app,
            ["--db", str(db_path), "check", "org/repo"],
        )

    assert result.exit_code == 0
    assert "integrity_events=0" in result.stdout
    assert "drift_detected=0" in result.stdout
    assert "run_id=99" in result.stdout


def test_export_requires_db(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_DB, raising=False)
    out = tmp_path / "out.jsonl"
    result = runner.invoke(app, ["export", "org/repo", "--out", str(out)])
    assert result.exit_code != 0
    assert (
        "--db" in result.stdout + result.stderr
        or ENV_DB in result.stdout + result.stderr
    )


def test_link_show_missing(tmp_path):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])
    result = runner.invoke(
        app,
        ["--db", str(db_path), "link", "show", "nosuch", "--provider", "pypi"],
    )
    assert result.exit_code == 1


def test_report_with_acknowledge_writes_checkpoint(tmp_path):
    db_path = tmp_path / "audit.db"
    out = tmp_path / "report.html"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    from datetime import datetime

    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.models import EventIn
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    repo = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
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
                    "merged_at": "2026-01-01T12:00:00+00:00",
                    "state": "closed",
                },
            ),
        ],
    )
    store.finish_run(run_id)
    conn.close()

    result = runner.invoke(
        app,
        [
            "--db",
            str(db_path),
            "report",
            "org/repo",
            "--out",
            str(out),
            "--acknowledge",
            "--as-of",
            "2026-06-01T00:00:00Z",
        ],
    )

    assert result.exit_code == 0
    assert out.exists()
    conn = connect(DbConfig(path=db_path))
    store = EventStore(conn)
    state = store.get_audit_state(repo)
    conn.close()
    assert state is not None
    assert state.checkpoint_at is not None
    assert state.profile_json is not None


def test_parse_sources_all():
    from augit.cli.collect_github import parse_sources

    assert parse_sources("all") == [
        "prs",
        "commits",
        "releases",
        "tags",
        "dependencies",
        "git_refs",
    ]
    assert parse_sources("prs,commits") == ["prs", "commits"]


def test_export_writes_jsonl_from_db(tmp_path):
    db_path = tmp_path / "audit.db"
    out = tmp_path / "events.jsonl"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    from datetime import datetime

    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.models import EventIn
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    repo = github_repo_key("org/repo")
    repo_id = store.ensure_repo(repo)
    run_id = store.start_run(repo_id, mode="incremental")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
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
                payload={"number": 1, "state": "open"},
            ),
        ],
    )
    store.finish_run(run_id)
    conn.close()

    result = runner.invoke(
        app,
        ["--db", str(db_path), "export", "org/repo", "--out", str(out)],
    )
    assert result.exit_code == 0
    lines = out.read_text("utf-8").strip().splitlines()
    assert len(lines) == 1
    assert '"event_type": "github_pull_request"' in lines[0]


def test_link_pypi_persists_package_link(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    data["info"]["home_page"] = "https://github.com/psf/requests"
    data["info"]["project_urls"] = {"Repository": "https://github.com/psf/requests"}
    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda _name: data,
    )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "link", "pypi", "requests"],
    )
    assert result.exit_code == 0

    show = runner.invoke(
        app,
        ["--db", str(db_path), "link", "show", "requests", "--provider", "pypi"],
    )
    assert show.exit_code == 0
    assert "psf/requests" in show.stdout or "github.com/psf/requests" in show.stdout


def test_collect_pypi_inserts_version_events(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    monkeypatch.setattr(
        "augit.collectors.pypi.fetch_pypi_json",
        lambda _name: data,
    )
    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda _name: data,
    )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "collect", "pypi", "requests", "--no-follow"],
    )
    assert result.exit_code == 0

    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    pkg_key = RepoKey(canonical_url="requests", provider="pypi")
    events = list(store.iter_events_for_repo(pkg_key))
    conn.close()
    assert len(events) == 2
    assert all(e["event_type"] == "pypi_release_version" for e in events)


def test_collect_auto_pypi_follows_github(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    data["info"]["home_page"] = "https://github.com/psf/requests"
    data["info"]["project_urls"] = {"Repository": "https://github.com/psf/requests"}
    monkeypatch.setattr(
        "augit.collectors.pypi.fetch_pypi_json",
        lambda _name: data,
    )
    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda _name: data,
    )

    class FakeClient:
        @classmethod
        def from_env(cls):
            return cls()

    monkeypatch.setattr(
        "augit.collect_linked.GitHubClient",
        FakeClient,
    )
    monkeypatch.setattr(
        "augit.collect_linked.collect_github_sources",
        lambda store, client, repo_key, sources: type(
            "R",
            (),
            {"inserted_by_source": {"prs": 1}, "run_ids": [1]},
        )(),
    )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "collect", "auto", "requests", "--sources", "prs"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "pypi pypi:requests" in result.stdout
    assert "github https://github.com/psf/requests" in result.stdout


def test_collect_maven_inserts_version_events(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = Path(__file__).parent / "fixtures" / "maven_gav_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    monkeypatch.setattr(
        "augit.collectors.maven.fetch_maven_versions",
        lambda _gav, rows=200: data,
    )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "collect", "maven", "com.example:demo", "--no-follow"],
    )
    assert result.exit_code == 0

    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    pkg_key = RepoKey(canonical_url="com.example:demo", provider="maven")
    events = list(store.iter_events_for_repo(pkg_key))
    conn.close()
    assert len(events) == 2
    assert all(e["event_type"] == "maven_release_version" for e in events)


def test_collect_npm_inserts_version_events(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    runner.invoke(app, ["db", "init", "--path", str(db_path)])

    fixture = Path(__file__).parent / "fixtures" / "npm_event_stream_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    monkeypatch.setattr(
        "augit.collectors.npm.fetch_npm_json",
        lambda _name: data,
    )
    monkeypatch.setattr(
        "augit.package_links.fetch_npm_json",
        lambda _name: data,
    )

    result = runner.invoke(
        app,
        ["--db", str(db_path), "collect", "npm", "event-stream", "--no-follow"],
    )
    assert result.exit_code == 0

    from augit.db import DbConfig, connect
    from augit.migrate import migrate
    from augit.store import EventStore

    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    pkg_key = RepoKey(canonical_url="event-stream", provider="npm")
    events = list(store.iter_events_for_repo(pkg_key))
    conn.close()
    assert len(events) == 2
    assert all(e["event_type"] == "npm_release_version" for e in events)
