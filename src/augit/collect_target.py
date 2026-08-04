"""Parse user-facing collect targets into provider + key."""

from __future__ import annotations

from dataclasses import dataclass

from augit.collectors.github_api import canonical_github_url, github_repo_key
from augit.collectors.maven import parse_gav
from augit.models import RepoKey


@dataclass(frozen=True)
class CollectTarget:
    """A resolved collect target."""

    provider: str  # github | pypi | maven
    key: RepoKey
    display: str


def parse_collect_target(raw: str) -> CollectTarget:
    """
    Accept GitHub owner/repo or URL, ``pypi:name``, ``maven:g:a``, bare GAV,
    or a bare PyPI package name.
    """
    s = raw.strip()
    if not s:
        raise ValueError("target must be non-empty")

    lower = s.lower()
    if lower.startswith("pypi:"):
        name = s.split(":", 1)[1].strip()
        if not name:
            raise ValueError("pypi target requires a package name")
        return CollectTarget(
            provider="pypi",
            key=RepoKey(canonical_url=name, provider="pypi"),
            display=f"pypi:{name}",
        )

    if lower.startswith("maven:"):
        gav = s.split(":", 1)[1].strip()
        g, a = parse_gav(gav)
        canon = f"{g}:{a}"
        return CollectTarget(
            provider="maven",
            key=RepoKey(canonical_url=canon, provider="maven"),
            display=f"maven:{canon}",
        )

    # Explicit GitHub URL or git@ form
    if "github.com" in lower or lower.startswith("git@github.com:"):
        key = github_repo_key(s)
        return CollectTarget(provider="github", key=key, display=key.canonical_url)

    # Maven GAV: exactly one colon separating group and artifact (group may
    # contain dots; artifact typically does not contain ':').
    if s.count(":") == 1 and "/" not in s:
        g, a = parse_gav(s)
        canon = f"{g}:{a}"
        return CollectTarget(
            provider="maven",
            key=RepoKey(canonical_url=canon, provider="maven"),
            display=f"maven:{canon}",
        )

    # owner/repo → GitHub (single slash, no spaces)
    if s.count("/") == 1 and " " not in s and not s.startswith("/"):
        owner, repo = s.split("/", 1)
        if owner and repo and ":" not in owner and ":" not in repo:
            try:
                key = github_repo_key(s)
            except ValueError as exc:
                raise ValueError(f"invalid GitHub target: {s}") from exc
            return CollectTarget(
                provider="github",
                key=key,
                display=canonical_github_url(s),
            )

    # Default: PyPI package name
    return CollectTarget(
        provider="pypi",
        key=RepoKey(canonical_url=s, provider="pypi"),
        display=f"pypi:{s}",
    )
