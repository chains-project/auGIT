import json
from pathlib import Path

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_commits import commit_to_event
from augit.signing import extract_openpgp_signer_key_id


def test_commit_to_event_normalizes_min_fields():
    fixture = Path(__file__).parent / "fixtures" / "github_commits_page1.json"
    commits = json.loads(fixture.read_text("utf-8"))

    repo_key = github_repo_key("org/repo")
    ev = commit_to_event(repo_key, "org/repo", commits[0])

    assert ev.event_type == "github_commit"
    assert ev.source_event_id == "commit:org/repo:aaa111"
    assert ev.payload["message_headline"] == "Fix thing"
    assert ev.payload["verified"] is True
    assert ev.payload["signer_key_id"] is None


def test_commit_to_event_extracts_personal_signing_key_id():
    verification = json.loads(
        (
            Path(__file__).parent / "fixtures" / "github_commit_verification.json"
        ).read_text("utf-8")
    )
    commit = {
        "sha": "deadbeef",
        "commit": {
            "author": {"email": "a@example.com", "date": "2026-05-01T10:00:00Z"},
            "committer": {"email": "c@example.com", "date": "2026-05-01T10:10:00Z"},
            "message": "Signed change",
            "verification": verification,
        },
        "author": {"login": "alice"},
        "committer": {"login": "alice"},
    }
    ev = commit_to_event(github_repo_key("org/repo"), "org/repo", commit)
    assert (
        extract_openpgp_signer_key_id(verification["signature"]) == "B5690EEEBB952194"
    )
    assert ev.payload["signer_key_id"] is None


def test_commit_to_event_handles_whitespace_only_message():
    commit = {
        "sha": "cafebabe",
        "commit": {
            "author": {"email": "a@example.com", "date": "2026-05-01T10:00:00Z"},
            "committer": {"email": "c@example.com", "date": "2026-05-01T10:10:00Z"},
            "message": "\n",
            "verification": {},
        },
        "author": {"login": "alice"},
        "committer": {"login": "alice"},
    }
    ev = commit_to_event(github_repo_key("org/repo"), "org/repo", commit)
    assert ev.payload["message_headline"] == ""
