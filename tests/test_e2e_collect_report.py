import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from augit.analysis.html_render import render_html
from augit.analysis.report_builder import ReportOptions, build_trust_report
from augit.cli.collect_github import collect_github_sources
from augit.collectors.github_api import github_repo_key


def _graphql_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text("utf-8"))


def test_collect_github_prs_then_build_trust_report(db_store):
    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture

    repo_key = github_repo_key("org/repo")
    result = collect_github_sources(db_store, client, repo_key, ["prs"])

    assert result.inserted_by_source["prs"] == 2
    events = list(db_store.iter_events_for_repo(repo_key))
    assert len(events) == 2
    assert all(e["event_type"] == "github_pull_request" for e in events)

    as_of = datetime(2026, 6, 1, tzinfo=UTC)
    report = build_trust_report(
        db_store,
        repo_key,
        options=ReportOptions(as_of=as_of, tail_days=90),
    )
    assert report.total_events == 2
    assert report.repo.canonical_url.endswith("org/repo")

    html = render_html(report)
    assert "<!DOCTYPE html>" in html
    assert "org/repo" in html
    assert "window / total events" in html
