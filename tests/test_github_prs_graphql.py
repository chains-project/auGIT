import json
from pathlib import Path
from unittest.mock import MagicMock

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_prs import collect_pull_requests, graphql_pr_node_to_event


def _graphql_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text("utf-8"))


def test_graphql_pr_node_to_event_maps_review_metadata():
    node = _graphql_fixture("github_graphql_prs_page1.json")["data"]["repository"][
        "pullRequests"
    ]["nodes"][0]
    repo_key = github_repo_key("org/repo")
    ev = graphql_pr_node_to_event(repo_key, "org/repo", node)

    assert ev.source_event_id == "pr:org/repo:12"
    assert ev.payload["author_login"] == "alice"
    assert ev.payload["state"] == "closed"
    assert ev.payload["base_branch"] == "main"
    assert ev.payload["merge_commit_sha"] == "abc"
    assert ev.payload["review_count"] == 2
    assert ev.payload["review_comment_count"] == 5
    assert ev.payload["review_states"] == ["APPROVED", "COMMENTED"]
    assert ev.payload["merged_by_login"] == "reviewer"


def test_collect_pull_requests_uses_graphql_not_rest_enrichment():
    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture
    client.get_json = MagicMock()

    repo_key = github_repo_key("org/repo")
    result = collect_pull_requests(client, repo_key=repo_key, cursor=None)

    assert len(result.events) == 2
    client.graphql.assert_called_once()
    client.get_json.assert_not_called()
    merged = next(e for e in result.events if e.payload["number"] == 12)
    assert merged.payload["review_comment_count"] == 5


def test_collect_pull_requests_advances_cursor_on_first_run():
    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture

    repo_key = github_repo_key("org/repo")
    result = collect_pull_requests(client, repo_key=repo_key, cursor=None)

    assert len(result.events) == 2
    assert result.cursor["updated_since"] == "2026-05-03T10:00:00Z"


def test_collect_pull_requests_stops_at_updated_since_cursor():
    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture

    repo_key = github_repo_key("org/repo")
    result = collect_pull_requests(
        client,
        repo_key=repo_key,
        cursor={"updated_since": "2026-05-02T00:00:00Z"},
    )

    assert len(result.events) == 1
    assert result.events[0].payload["number"] == 12
    assert result.cursor["updated_since"] == "2026-05-03T10:00:00Z"
