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

PULL_REQUESTS_QUERY = """
query($owner: String!, $repo: String!, $after: String, $first: Int!) {
  rateLimit {
    remaining
    resetAt
  }
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: $first
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        state
        createdAt
        updatedAt
        closedAt
        mergedAt
        author { login }
        mergeCommit { oid }
        baseRefName
        headRefOid
        mergedBy { login }
        reviews(first: 100) {
          totalCount
          nodes {
            state
            comments { totalCount }
          }
        }
      }
    }
  }
}
"""


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _rest_state(state: str | None, merged_at: str | None) -> str | None:
    if not state:
        return None
    normalized = state.lower()
    if normalized == "merged" or merged_at:
        return "closed"
    return normalized


def _review_comment_count(reviews: dict[str, Any]) -> int:
    nodes = reviews.get("nodes") or []
    return sum((n.get("comments") or {}).get("totalCount") or 0 for n in nodes)


def _max_iso_timestamp(current: str | None, candidate: str | None) -> str | None:
    if not candidate:
        return current
    if current is None or candidate > current:
        return candidate
    return current


def graphql_pr_node_to_event(
    repo: RepoKey,
    owner_repo: str,
    node: dict[str, Any],
) -> EventIn:
    number = int(node["number"])
    merged_at = node.get("mergedAt")
    reviews = node.get("reviews") or {}
    review_nodes = reviews.get("nodes") or []
    review_states = [n.get("state") for n in review_nodes if n.get("state")]

    merged_by_login = (node.get("mergedBy") or {}).get("login")

    payload: dict[str, Any] = {
        "number": number,
        "state": _rest_state(node.get("state"), merged_at),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "closed_at": node.get("closedAt"),
        "merged_at": merged_at,
        "author_login": (node.get("author") or {}).get("login"),
        "merge_commit_sha": (node.get("mergeCommit") or {}).get("oid"),
        "base_branch": node.get("baseRefName"),
        "head_sha": node.get("headRefOid"),
    }
    if merged_at:
        payload["review_count"] = reviews.get("totalCount")
        payload["review_states"] = review_states
        payload["merged_by_login"] = merged_by_login
        payload["review_comment_count"] = _review_comment_count(reviews)

    return EventIn(
        repo=repo,
        category="contributor",
        event_type="github_pull_request",
        source="github_api",
        source_event_id=f"pr:{owner_repo}:{number}",
        source_timestamp=_dt(node.get("createdAt")),
        payload=payload,
    )


def pr_to_event(
    repo: RepoKey,
    owner_repo: str,
    pr: dict[str, Any],
) -> EventIn:
    """Map a REST-shaped pull request dict (used in unit tests)."""
    number = int(pr["number"])
    payload = {
        "number": number,
        "state": pr.get("state"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "closed_at": pr.get("closed_at"),
        "merged_at": pr.get("merged_at"),
        "author_login": (pr.get("user") or {}).get("login"),
        "merge_commit_sha": pr.get("merge_commit_sha"),
        "base_branch": ((pr.get("base") or {}).get("ref")),
        "head_sha": ((pr.get("head") or {}).get("sha")),
    }
    return EventIn(
        repo=repo,
        category="contributor",
        event_type="github_pull_request",
        source="github_api",
        source_event_id=f"pr:{owner_repo}:{number}",
        source_timestamp=_dt(pr.get("created_at")),
        payload=payload,
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def _fetch_pr_page(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    after: str | None,
    per_page: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    body = client.graphql(
        PULL_REQUESTS_QUERY,
        {"owner": owner, "repo": repo, "after": after, "first": per_page},
    )
    repository = (body.get("data") or {}).get("repository")
    if not repository:
        return {}, []
    connection = repository.get("pullRequests") or {}
    return connection, connection.get("nodes") or []


def collect_pull_requests(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    per_page: int = 100,
    max_pages: int = 50,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    updated_since = (cursor or {}).get("updated_since")

    events: list[EventIn] = []
    latest_seen: str | None = updated_since
    after: str | None = None
    pages = 0
    total: int | None = None
    stop = False

    with item_progress("pull requests", total) as progress:
        while pages < max_pages and not stop:
            connection, nodes = _fetch_pr_page(
                client,
                owner=owner,
                repo=repo,
                after=after,
                per_page=per_page,
            )
            if not nodes:
                break

            if total is None:
                raw_total = connection.get("totalCount")
                if isinstance(raw_total, int):
                    total = min(raw_total, max_pages * per_page)
                    progress.total = total
                    progress.refresh()

            for node in nodes:
                pr_updated = node.get("updatedAt")
                if pr_updated:
                    latest_seen = _max_iso_timestamp(latest_seen, pr_updated)

                if updated_since and pr_updated and pr_updated <= updated_since:
                    stop = True
                    break

                events.append(graphql_pr_node_to_event(repo_key, owner_repo, node))
                progress.update(1)

            pages += 1
            page_info = connection.get("pageInfo") or {}
            if stop or not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

    return CollectResult(
        events=events,
        cursor={"updated_since": latest_seen or updated_since},
    )
