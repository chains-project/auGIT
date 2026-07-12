from typing import Any, TypedDict

from augit.collectors.github_api import canonical_github_url, github_owner_repo
from augit.models import RepoKey


class ComparableRepoIdentity(TypedDict):
    canonical_url: str
    full_name: str


def normalize_repo_identity(
    ident: dict[str, Any],
    *,
    repo_key: RepoKey | None = None,
) -> ComparableRepoIdentity:
    """
    Project any repo_identity blob onto a fixed schema for equality checks.

    full_name is taken from the payload when present, otherwise derived from
    canonical_url (or RepoKey) so audit-log and API refetches use the same shape.
    """
    raw_url = ident.get("canonical_url") or ident.get("html_url")
    if raw_url:
        url = canonical_github_url(str(raw_url))
    elif repo_key is not None:
        url = repo_key.canonical_url
    else:
        raise ValueError("repo identity requires canonical_url or repo_key")

    full_name = ident.get("full_name")
    if not full_name:
        full_name = github_owner_repo(RepoKey(canonical_url=url, provider="github"))

    return ComparableRepoIdentity(canonical_url=url, full_name=str(full_name))
