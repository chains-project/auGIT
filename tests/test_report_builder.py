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
