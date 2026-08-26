from datetime import UTC, datetime

from augit.analysis.html_render import render_html
from augit.analysis.report_builder import build_trust_report
from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import EventIn
from augit.store import EventStore


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def test_build_trust_report_html(tmp_path):
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
                event_type="integrity_drift",
                source="refetch_compare",
                source_event_id="warn:1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={
                    "subtype": "tag_retargeted",
                    "severity": "high",
                    "expected": {"tag": "v1", "sha": "aaa"},
                    "observed": {"tag": "v1", "sha": "bbb"},
                },
            ),
            EventIn(
                repo=repo_key,
                category="contributor",
                event_type="github_pull_request",
                source="github_api",
                source_event_id="pr:1",
                source_timestamp=_now(),
                observed_at=_now(),
                payload={
                    "number": 12,
                    "author_login": "alice",
                    "merged_at": "2026-01-01T12:00:00+00:00",
                    "state": "closed",
                    "merge_commit_sha": "abc",
                },
            ),
        ],
    )
    store.finish_run(run_id)

    report = build_trust_report(store, repo_key)
    assert report.status == "findings"
    assert report.total_events == 2
    # Integrity drift events are excluded from compare-window counts.
    assert report.compare_window_events == 1
    assert len(report.findings) >= 1
    assert any(f.metric_id == "history_integrity" for f in report.findings)

    html = render_html(report)
    assert "<!DOCTYPE html>" in html
    assert "window / total events" in html
    assert "History drift detected" in html
    integrity = next(f for f in report.findings if f.metric_id == "history_integrity")
    assert integrity.title in html
    assert "Baseline" in html
    assert "Observed in window" not in html
    assert "badge-warning" not in html
    assert "Alerts" not in html
    assert "Integrity" in html


def test_report_merges_linked_github_tags_for_pypi_package(tmp_path):
    from datetime import timedelta

    from augit.analysis.report_builder import ReportOptions
    from augit.models import RepoKey

    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    now = datetime(2026, 7, 31, tzinfo=UTC)
    old = now - timedelta(days=200)
    recent = now - timedelta(days=10)
    pkg = RepoKey(canonical_url="requests", provider="pypi")
    gh = github_repo_key("psf/requests")
    store.upsert_package_link(
        pkg, gh, source_field="project_urls.Source", raw_url=gh.canonical_url
    )

    pkg_id = store.ensure_repo(pkg)
    gh_id = store.ensure_repo(gh)
    run_pkg = store.start_run(pkg_id, mode="incremental")
    store.append_events(
        run_pkg,
        [
            EventIn(
                repo=pkg,
                category="release",
                event_type="pypi_release_version",
                source="registry",
                source_event_id="pypi:requests:2.30.0",
                source_timestamp=old,
                observed_at=old,
                payload={
                    "version": "2.30.0",
                    "package": "requests",
                    "published_at": old.isoformat().replace("+00:00", "Z"),
                    "uploaders": ["alice"],
                },
            ),
            EventIn(
                repo=pkg,
                category="release",
                event_type="pypi_release_version",
                source="registry",
                source_event_id="pypi:requests:2.34.2",
                source_timestamp=recent,
                observed_at=recent,
                payload={
                    "version": "2.34.2",
                    "package": "requests",
                    "published_at": recent.isoformat().replace("+00:00", "Z"),
                    "uploaders": ["alice"],
                },
            ),
        ],
    )
    store.finish_run(run_pkg)

    run_gh = store.start_run(gh_id, mode="incremental")
    store.append_events(
        run_gh,
        [
            EventIn(
                repo=gh,
                category="release",
                event_type="github_tag",
                source="github_api",
                source_event_id="tag:psf/requests:v2.30.0",
                source_timestamp=None,
                observed_at=now,
                payload={"tag_name": "v2.30.0", "sha": "aaa"},
            ),
            EventIn(
                repo=gh,
                category="release",
                event_type="github_tag",
                source="github_api",
                source_event_id="tag:psf/requests:v2.34.2",
                source_timestamp=None,
                observed_at=now,
                payload={"tag_name": "v2.34.2", "sha": "bbb"},
            ),
            EventIn(
                repo=gh,
                category="release",
                event_type="github_release",
                source="github_api",
                source_event_id="release:psf/requests:1",
                source_timestamp=old,
                observed_at=old,
                payload={
                    "tag_name": "v2.30.0",
                    "author_login": "alice",
                    "published_at": old.isoformat().replace("+00:00", "Z"),
                },
            ),
        ],
    )
    store.finish_run(run_gh)

    report = build_trust_report(
        store,
        pkg,
        options=ReportOptions(mode="initial", tail_days=90, as_of=now),
    )
    missing = [
        f
        for f in report.findings
        if f.metric_id == "unusual_release_pattern"
        and f.title == "Registry version without matching tag"
    ]
    assert missing == []
    assert report.total_events >= 5
