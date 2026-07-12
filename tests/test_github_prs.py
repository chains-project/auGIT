import json
from pathlib import Path

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_prs import pr_to_event


def test_pr_to_event_normalizes_min_fields():
    fixture = Path(__file__).parent / "fixtures" / "github_prs_page1.json"
    prs = json.loads(fixture.read_text("utf-8"))

    repo_key = github_repo_key("org/repo")
    ev = pr_to_event(repo_key, "org/repo", prs[0])

    assert ev.category == "contributor"
    assert ev.event_type == "github_pull_request"
    assert ev.source == "github_api"
    assert ev.source_event_id == "pr:org/repo:12"
    assert ev.payload["author_login"] == "alice"
    assert ev.payload["base_branch"] == "main"
