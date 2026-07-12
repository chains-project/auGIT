from typing import Any

from augit.collectors.git_refs import collect_git_refs
from augit.collectors.github_api import (
    GitHubClient,
    github_owner_repo,
    parse_owner_repo,
)
from augit.integrity_identity import normalize_repo_identity
from augit.models import IntegrityRefetchView, RepoKey


def _pr_record(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr_number": pr.get("number"),
        "merged_at": pr.get("merged_at"),
        "merge_commit_sha": pr.get("merge_commit_sha"),
        "state": pr.get("state"),
    }


def _release_record(rel: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_id": rel.get("id"),
        "tag_name": rel.get("tag_name"),
        "published_at": rel.get("published_at"),
        "author": (rel.get("author") or {}).get("login"),
    }


def fetch_github_api_subjects(
    client: GitHubClient,
    owner_repo: str,
    *,
    max_pages_prs: int = 50,
    max_pages_releases: int = 50,
    max_pages_tags: int = 50,
) -> dict[str, Any]:
    owner, repo = parse_owner_repo(owner_repo)

    pull_requests: list[dict[str, Any]] = []
    pages = 0
    for page in client.paginate(
        f"/repos/{owner}/{repo}/pulls",
        params={"state": "all", "per_page": 100},
    ):
        pages += 1
        if pages > max_pages_prs or not isinstance(page, list):
            break
        for pr in page:
            pull_requests.append(_pr_record(pr))

    releases: list[dict[str, Any]] = []
    pages = 0
    for page in client.paginate(
        f"/repos/{owner}/{repo}/releases", params={"per_page": 100}
    ):
        pages += 1
        if pages > max_pages_releases or not isinstance(page, list):
            break
        for rel in page:
            releases.append(_release_record(rel))

    tag_targets: dict[str, str] = {}
    pages = 0
    for page in client.paginate(
        f"/repos/{owner}/{repo}/tags", params={"per_page": 100}
    ):
        pages += 1
        if pages > max_pages_tags or not isinstance(page, list):
            break
        for tag in page:
            name = tag.get("name")
            sha = (tag.get("commit") or {}).get("sha")
            if name and sha:
                tag_targets[name] = sha

    repo_data, _ = client.get_json(f"/repos/{owner}/{repo}")
    repo_identity = {
        "canonical_url": repo_data.get("html_url"),
        "full_name": repo_data.get("full_name"),
        "owner_login": (repo_data.get("owner") or {}).get("login"),
        "default_branch": repo_data.get("default_branch"),
    }

    return {
        "pull_requests": pull_requests,
        "releases": releases,
        "tag_targets": tag_targets,
        "repo_identity": repo_identity,
    }


def build_integrity_refetch_view(
    client: GitHubClient,
    repo_key: RepoKey,
    *,
    remote: str | None = None,
    branches: list[str] | None = None,
    use_git: bool = True,
) -> IntegrityRefetchView:
    """
    Build a refetched view using the same subjects as the audit trail:
    - GitHub API subjects (PRs, releases, tags, repo identity)
    - git refs-only subjects (branch tips + tag targets via `git ls-remote`)
    """
    owner_repo = github_owner_repo(repo_key)
    api = fetch_github_api_subjects(client, owner_repo)

    branch_reachability: dict[str, list[str]] = {}
    git_tags: dict[str, str] = {}

    if use_git:
        remote_url = remote or f"{repo_key.canonical_url}.git"
        ref_events = collect_git_refs(
            repo_key, remote=remote_url, branches=branches
        ).events
        for ev in ref_events:
            payload = ev.payload or {}
            if ev.event_type == "git_branch_tip":
                b = payload.get("branch")
                sha = payload.get("sha")
                if b and sha:
                    branch_reachability[str(b)] = [str(sha)]
            elif ev.event_type == "git_tag_target":
                t = payload.get("tag")
                sha = payload.get("sha")
                if t and sha:
                    git_tags[str(t)] = str(sha)

    # Prefer git tag SHAs (peeled); use API tags for any missing names.
    tag_targets = {**api["tag_targets"], **git_tags}

    return IntegrityRefetchView(
        branch_reachability=branch_reachability,
        tag_targets=tag_targets,
        pull_requests=api["pull_requests"],
        releases=api["releases"],
        repo_identity=normalize_repo_identity(api["repo_identity"], repo_key=repo_key),
    )
