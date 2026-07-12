from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.collectors.github_api import (
    GitHubClient,
    github_owner_repo,
    parse_owner_repo,
)
from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey
from augit.signing import signing_key_id_from_verification


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def commit_to_event(repo: RepoKey, owner_repo: str, commit: dict[str, Any]) -> EventIn:
    sha = commit["sha"]
    commit_obj = commit.get("commit") or {}
    author_obj = commit_obj.get("author") or {}
    committer_obj = commit_obj.get("committer") or {}

    raw_message = commit_obj.get("message") or ""
    # Some fixtures / sources may contain literal backslash-n sequences.
    normalized_message = raw_message.replace("\\n", "\n")
    headline_lines = normalized_message.strip().splitlines()

    verification = commit_obj.get("verification") or {}
    payload = {
        "sha": sha,
        "author_login": (commit.get("author") or {}).get("login"),
        "committer_login": (commit.get("committer") or {}).get("login"),
        "author_email": author_obj.get("email"),
        "committer_email": committer_obj.get("email"),
        "message_headline": headline_lines[0] if headline_lines else "",
        "verified": verification.get("verified"),
        "verification_reason": verification.get("reason"),
        "signer_key_id": signing_key_id_from_verification(verification),
        "parents_count": len(commit.get("parents") or []),
    }

    # Prefer committer date for ordering; author date can be older.
    ts = _dt(committer_obj.get("date")) or _dt(author_obj.get("date"))

    return EventIn(
        repo=repo,
        category="contributor",
        event_type="github_commit",
        source="github_api",
        source_event_id=f"commit:{owner_repo}:{sha}",
        source_timestamp=ts,
        payload=payload,
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def collect_commits(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    per_page: int = 100,
    max_pages: int = 50,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    since = (cursor or {}).get("since")
    params = {"per_page": per_page, "since": since} if since else {"per_page": per_page}
    path = f"/repos/{owner}/{repo}/commits"

    events: list[EventIn] = []
    newest_ts: str | None = None

    pages = 0
    with item_progress("commits", None) as progress:
        for page_data in client.paginate(path, params=params):
            pages += 1
            if pages > max_pages:
                break
            if not isinstance(page_data, list):
                break
            for c in page_data:
                commit_obj = c.get("commit") or {}
                committer = (commit_obj.get("committer") or {}).get("date")
                author = (commit_obj.get("author") or {}).get("date")
                ts = committer or author
                if ts and (newest_ts is None or ts > newest_ts):
                    newest_ts = ts
                events.append(commit_to_event(repo_key, owner_repo, c))
                progress.update(1)

    # since should move forward; GitHub expects ISO 8601.
    return CollectResult(events=events, cursor={"since": newest_ts or since})
