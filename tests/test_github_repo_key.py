import pytest

from augit.collectors.github_api import (
    canonical_github_url,
    github_owner_repo,
    github_repo_key,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("org/repo", "https://github.com/org/repo"),
        ("https://github.com/org/repo", "https://github.com/org/repo"),
        ("https://github.com/org/repo/", "https://github.com/org/repo"),
        ("https://github.com/org/repo.git", "https://github.com/org/repo"),
        ("git@github.com:org/repo.git", "https://github.com/org/repo"),
    ],
)
def test_canonical_github_url(raw: str, expected: str) -> None:
    assert canonical_github_url(raw) == expected


def test_github_repo_key_and_owner_repo_roundtrip() -> None:
    key = github_repo_key("org/repo")
    assert key.canonical_url == "https://github.com/org/repo"
    assert key.provider == "github"
    assert github_owner_repo(key) == "org/repo"


def test_github_owner_repo_accepts_canonical_url_input() -> None:
    key = github_repo_key("https://github.com/foo/bar")
    assert github_owner_repo(key) == "foo/bar"
