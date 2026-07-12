import json
from pathlib import Path

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_releases import release_to_event, tag_to_event


def test_release_to_event_normalizes_min_fields():
    fixture = Path(__file__).parent / "fixtures" / "github_releases_page1.json"
    rels = json.loads(fixture.read_text("utf-8"))

    repo_key = github_repo_key("org/repo")
    ev = release_to_event(repo_key, "org/repo", rels[0])

    assert ev.category == "release"
    assert ev.event_type == "github_release"
    assert ev.source_event_id == "release:org/repo:99"
    assert ev.payload["tag_name"] == "v1.0.0"


def test_tag_to_event_normalizes_min_fields():
    fixture = Path(__file__).parent / "fixtures" / "github_tags_page1.json"
    tags = json.loads(fixture.read_text("utf-8"))

    repo_key = github_repo_key("org/repo")
    ev = tag_to_event(repo_key, "org/repo", tags[0])

    assert ev.event_type == "github_tag"
    assert ev.source_event_id == "tag:org/repo:v1.0.0"
    assert ev.payload["sha"] == "abc"
