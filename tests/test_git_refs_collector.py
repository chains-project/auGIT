from unittest.mock import patch

from augit.collectors.git_refs import _parse_ls_remote, collect_git_refs
from augit.collectors.github_api import github_repo_key


def test_parse_ls_remote_heads_and_peeled_tags():
    output = "\n".join(
        [
            "deadbeef\trefs/heads/main",
            "cafebabe\trefs/tags/v1.0.0",
            "feedface\trefs/tags/v1.0.0^{}",
        ]
    )
    heads, tags = _parse_ls_remote(output)
    assert heads == {"main": "deadbeef"}
    assert tags == {"v1.0.0": "feedface"}


def test_collect_git_refs_emits_branch_and_tag_events():
    repo_key = github_repo_key("org/repo")
    ls_output = "\n".join(
        [
            "deadbeef\trefs/heads/main",
            "feedface\trefs/tags/v1.0.0^{}",
        ]
    )

    with patch("augit.collectors.git_refs._run", return_value=ls_output):
        result = collect_git_refs(repo_key, remote="https://github.com/org/repo.git")

    assert len(result.events) == 2
    types = {e.event_type for e in result.events}
    assert types == {"git_branch_tip", "git_tag_target"}
    assert all(e.source == "git" for e in result.events)
    assert result.events[0].source_event_id.startswith("branch_tip:")
    assert result.events[1].source_event_id.startswith("tag_target:")
