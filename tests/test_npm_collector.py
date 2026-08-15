import json
from pathlib import Path
from unittest.mock import patch
import urllib.error
import urllib.request

from augit.collectors.npm import collect_npm_versions
from augit.package_links import github_url_from_npm_repository, link_npm_package
from augit.models import RepoKey
from augit.store import EventStore


def test_collect_npm_versions_emits_name_version_events():
    fixture = Path(__file__).parent / "fixtures" / "npm_event_stream_min.json"
    data = json.loads(fixture.read_text("utf-8"))

    result = collect_npm_versions(package_name="event-stream", cursor=None, npm_json=data)
    assert len(result.events) == 2
    assert result.events[0].source_event_id.startswith("npm:event-stream:")
    assert result.cursor["versions"] == ["3.3.4", "4.0.1"]
    assert result.events[1].payload["author_login"] == "right9ctrl"


def test_collect_npm_versions_emits_missing_event_on_404():
    def raise_404(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://registry.npmjs.org/missing-pkg",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    with patch.object(urllib.request, "urlopen", side_effect=raise_404):
        result = collect_npm_versions(package_name="missing-pkg", cursor=None)
    assert any(e.event_type == "npm_package_missing" for e in result.events)


def test_github_url_from_npm_repository_parses_git_plus_https():
    parsed = github_url_from_npm_repository(
        {"type": "git", "url": "git+https://github.com/dominictarr/event-stream.git"}
    )
    assert parsed is not None
    assert parsed[1] == "https://github.com/dominictarr/event-stream"


def test_link_npm_package(db_store):
    fixture = Path(__file__).parent / "fixtures" / "npm_event_stream_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    store: EventStore = db_store
    link = link_npm_package(store, "event-stream", npm_data=data)
    assert link.linked is True
    assert link.github_key == RepoKey(
        canonical_url="https://github.com/dominictarr/event-stream",
        provider="github",
    )
