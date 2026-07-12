import json
from pathlib import Path
from unittest.mock import MagicMock

from augit.cli.collect_github import collect_github_sources
from augit.collectors.github_api import github_repo_key


def _graphql_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text("utf-8"))


def test_collect_github_reuses_prs_for_dependencies(db_store):
    fixture = _graphql_fixture("github_graphql_prs_page1.json")
    client = MagicMock()
    client.graphql.return_value = fixture
    client.get_json.return_value = ([], {})

    repo_key = github_repo_key("org/repo")
    result = collect_github_sources(
        db_store,
        client,
        repo_key,
        ["prs", "dependencies"],
    )

    assert result.inserted_by_source["prs"] == 2
    list_pulls_calls = [
        call[0][0]
        for call in client.get_json.call_args_list
        if call[0][0].endswith("/pulls")
    ]
    assert list_pulls_calls == []
