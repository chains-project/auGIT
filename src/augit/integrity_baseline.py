from typing import Any

from augit.integrity_identity import normalize_repo_identity
from augit.models import IntegrityRefetchView, RepoKey
from augit.store import EventStore


def audit_log_view_has_content(view: IntegrityRefetchView) -> bool:
    """True when the audit log has subjects to compare against."""
    if view.branch_reachability:
        return True
    if view.tag_targets:
        return True
    if view.pull_requests:
        return True
    if view.releases:
        return True
    return False


def build_view_from_audit_log(
    store: EventStore, repo_key: RepoKey
) -> IntegrityRefetchView:
    """Reconstruct audit-trail subjects from stored collection events."""
    branch_tips: dict[str, str] = {}
    tag_targets: dict[str, str] = {}
    pull_requests: list[dict[str, Any]] = []
    releases: list[dict[str, Any]] = []

    for row in store.iter_events_for_repo(repo_key):
        et = row["event_type"]
        payload = row["payload"] or {}

        if et == "git_branch_tip":
            branch = payload.get("branch")
            sha = payload.get("sha")
            if branch and sha:
                branch_tips[str(branch)] = str(sha)
        elif et in ("git_tag_target", "github_tag"):
            name = payload.get("tag") or payload.get("tag_name")
            sha = payload.get("sha")
            if name and sha:
                tag_targets[str(name)] = str(sha)
        elif et == "github_pull_request":
            number = payload.get("number")
            if number is not None:
                pull_requests.append(
                    {
                        "pr_number": number,
                        "merged_at": payload.get("merged_at"),
                        "merge_commit_sha": payload.get("merge_commit_sha"),
                    }
                )
        elif et == "github_release":
            rid = payload.get("release_id")
            if rid is not None:
                releases.append(
                    {
                        "release_id": rid,
                        "tag_name": payload.get("tag_name"),
                        "published_at": payload.get("published_at"),
                        "author": payload.get("author_login"),
                    }
                )

    branch_reachability = {branch: [sha] for branch, sha in sorted(branch_tips.items())}

    return IntegrityRefetchView(
        branch_reachability=branch_reachability,
        tag_targets=tag_targets,
        pull_requests=pull_requests,
        releases=releases,
        repo_identity=normalize_repo_identity({}, repo_key=repo_key),
    )
