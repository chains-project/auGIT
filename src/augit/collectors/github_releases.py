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


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def release_to_event(repo: RepoKey, owner_repo: str, rel: dict[str, Any]) -> EventIn:
    rid = int(rel["id"])
    payload = {
        "release_id": rid,
        "tag_name": rel.get("tag_name"),
        "target_commitish": rel.get("target_commitish"),
        "published_at": rel.get("published_at"),
        "author_login": (rel.get("author") or {}).get("login"),
        "draft": rel.get("draft"),
        "prerelease": rel.get("prerelease"),
    }
    return EventIn(
        repo=repo,
        category="release",
        event_type="github_release",
        source="github_api",
        source_event_id=f"release:{owner_repo}:{rid}",
        source_timestamp=_dt(rel.get("published_at")) or _dt(rel.get("created_at")),
        payload=payload,
    )


def tag_to_event(repo: RepoKey, owner_repo: str, tag: dict[str, Any]) -> EventIn:
    name = tag.get("name")
    sha = ((tag.get("commit") or {}).get("sha")) if isinstance(tag, dict) else None
    payload = {"tag_name": name, "sha": sha}
    return EventIn(
        repo=repo,
        category="release",
        event_type="github_tag",
        source="github_api",
        source_event_id=f"tag:{owner_repo}:{name}",
        source_timestamp=None,
        payload=payload,
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def _max_iso_timestamp(current: str | None, candidate: str | None) -> str | None:
    if not candidate:
        return current
    if current is None or candidate > current:
        return candidate
    return current


def collect_releases(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    per_page: int = 100,
    max_pages: int = 50,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    published_since = (cursor or {}).get("published_since")
    params = {"per_page": per_page}
    path = f"/repos/{owner}/{repo}/releases"
    events: list[EventIn] = []
    latest_seen: str | None = published_since

    pages = 0
    with item_progress("releases", None) as progress:
        for page_data in client.paginate(path, params=params):
            pages += 1
            if pages > max_pages:
                break
            if not isinstance(page_data, list):
                break
            for rel in page_data:
                published = rel.get("published_at") or rel.get("created_at")
                if published:
                    latest_seen = _max_iso_timestamp(latest_seen, published)
                if published_since and published and published <= published_since:
                    return CollectResult(
                        events=events,
                        cursor={"published_since": latest_seen or published_since},
                    )
                events.append(release_to_event(repo_key, owner_repo, rel))
                progress.update(1)

    return CollectResult(
        events=events, cursor={"published_since": latest_seen or published_since}
    )


def collect_tags(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    per_page: int = 100,
    max_pages: int = 50,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    prev_hash = (cursor or {}).get("list_hash")
    tags: list[dict[str, Any]] = []
    params = {"per_page": per_page}
    path = f"/repos/{owner}/{repo}/tags"

    pages = 0
    with item_progress("tags", None) as progress:
        for page_data in client.paginate(path, params=params):
            pages += 1
            if pages > max_pages:
                break
            if not isinstance(page_data, list):
                break
            tags.extend(page_data)
            progress.update(len(page_data))

    list_hash = str(
        hash(tuple((t.get("name"), (t.get("commit") or {}).get("sha")) for t in tags))
    )
    if prev_hash is not None and list_hash == prev_hash:
        return CollectResult(events=[], cursor={"list_hash": list_hash})

    events = [tag_to_event(repo_key, owner_repo, t) for t in tags]
    return CollectResult(events=events, cursor={"list_hash": list_hash})
