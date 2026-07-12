from dataclasses import dataclass
from typing import Any, Literal

from augit.collectors.git_refs import collect_git_refs
from augit.collectors.github_api import GitHubClient
from augit.collectors.github_commits import collect_commits
from augit.collectors.github_dependencies import collect_dependency_changes
from augit.collectors.github_prs import collect_pull_requests
from augit.collectors.github_releases import collect_releases, collect_tags
from augit.models import RepoKey
from augit.store import EventStore

GitHubSource = Literal["prs", "commits", "releases", "tags", "dependencies", "git_refs"]
ALL_SOURCES: tuple[GitHubSource, ...] = (
    "prs",
    "commits",
    "releases",
    "tags",
    "dependencies",
    "git_refs",
)


def parse_sources(value: str) -> list[GitHubSource]:
    if value.strip().lower() == "all":
        return list(ALL_SOURCES)
    parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    valid = set(ALL_SOURCES)
    unknown = [p for p in parts if p not in valid]
    if unknown:
        raise ValueError(
            f"Unknown sources: {unknown}. Use all or comma-separated: {', '.join(ALL_SOURCES)}"
        )
    return parts  # type: ignore[return-value]


@dataclass(frozen=True)
class CollectGithubResult:
    inserted_by_source: dict[str, int]
    run_ids: list[int]


def _merged_prs_from_pr_events(events: list) -> list[dict[str, Any]]:
    """Build REST-shaped merged PR dicts from GraphQL-collected PR events."""
    merged: list[dict[str, Any]] = []
    for event in events:
        payload = event.payload or {}
        if not payload.get("merged_at"):
            continue
        merged.append(
            {
                "number": payload["number"],
                "merged_at": payload.get("merged_at"),
                "merge_commit_sha": payload.get("merge_commit_sha"),
                "user": {"login": payload.get("author_login")},
            }
        )
    return merged


def collect_github_sources(
    store: EventStore,
    client: GitHubClient,
    repo_key: RepoKey,
    sources: list[GitHubSource],
) -> CollectGithubResult:
    repo_id = store.ensure_repo(repo_key)
    inserted_by_source: dict[str, int] = {}
    run_ids: list[int] = []
    merged_pr_hints: list[dict[str, Any]] | None = None

    collectors = {
        "prs": ("github_prs", collect_pull_requests),
        "commits": ("github_commits", collect_commits),
        "releases": ("github_releases", collect_releases),
        "tags": ("github_tags", collect_tags),
        "dependencies": ("github_dependencies", collect_dependency_changes),
        "git_refs": (
            "git_refs",
            lambda _client, *, repo_key, cursor: collect_git_refs(
                repo_key, remote=f"{repo_key.canonical_url}.git"
            ),
        ),
    }

    for source in sources:
        cursor_key, collect_fn = collectors[source]
        run_id = store.start_run(repo_id, mode="incremental")
        cursor = store.get_cursor(repo_key, cursor_key)
        if source == "dependencies":
            result = collect_dependency_changes(
                client,
                repo_key=repo_key,
                cursor=cursor,
                merged_prs=merged_pr_hints,
            )
        else:
            result = collect_fn(client, repo_key=repo_key, cursor=cursor)
        if source == "prs":
            merged_pr_hints = _merged_prs_from_pr_events(result.events)
        inserted = store.append_events(run_id, result.events)
        store.set_cursor(repo_key, cursor_key, result.cursor)
        store.finish_run(run_id)
        inserted_by_source[source] = inserted
        run_ids.append(run_id)

    return CollectGithubResult(inserted_by_source=inserted_by_source, run_ids=run_ids)
