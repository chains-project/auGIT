import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from augit.models import EventIn, RepoKey


def _run(cmd: list[str]) -> str:
    out = subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return out.stdout


def _owner_repo_from_remote(remote: str) -> str | None:
    """
    Best-effort extract owner/repo from common GitHub remote URL formats.
    Used only for stable source_event_id formatting.
    """
    s = remote.strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]
    if s.startswith("git@github.com:"):
        path = s[len("git@github.com:") :]
        return path if "/" in path else None
    try:
        parsed = urlparse(s)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return None
    path = (parsed.path or "").strip("/")
    return path if "/" in path else None


def _parse_ls_remote(output: str) -> tuple[dict[str, str], dict[str, str]]:
    heads: dict[str, str] = {}
    tags_raw: dict[str, str] = {}
    tags_peeled: dict[str, str] = {}

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, ref = line.split("\t", 1)
        sha = sha.strip()
        ref = ref.strip()

        if ref.startswith("refs/heads/"):
            name = ref[len("refs/heads/") :]
            if name:
                heads[name] = sha
            continue

        if ref.startswith("refs/tags/"):
            name = ref[len("refs/tags/") :]
            if not name:
                continue
            if name.endswith("^{}"):
                tags_peeled[name[:-3]] = sha
            else:
                tags_raw[name] = sha

    # Prefer peeled when present.
    tags = {**tags_raw, **tags_peeled}
    return heads, tags


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def collect_git_refs(
    repo_key: RepoKey,
    *,
    remote: str,
    branches: list[str] | None = None,
) -> CollectResult:
    """
    Refs-only git collector: uses `git ls-remote` to record branch tips and tag targets.

    Emits:
    - event_type=git_branch_tip (source=git)
    - event_type=git_tag_target (source=git)
    """
    out = _run(["git", "ls-remote", "--heads", "--tags", remote])
    heads, tags = _parse_ls_remote(out)

    if branches:
        allow = set(branches)
        heads = {k: v for k, v in heads.items() if k in allow}

    owner_repo = _owner_repo_from_remote(remote) or repo_key.canonical_url

    events: list[EventIn] = []
    for branch, sha in sorted(heads.items()):
        events.append(
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_branch_tip",
                source="git",
                source_event_id=f"branch_tip:{owner_repo}:{branch}:{sha}",
                source_timestamp=None,
                payload={"branch": branch, "sha": sha, "remote": remote},
            )
        )

    for tag, sha in sorted(tags.items()):
        events.append(
            EventIn(
                repo=repo_key,
                category="integrity",
                event_type="git_tag_target",
                source="git",
                source_event_id=f"tag_target:{owner_repo}:{tag}:{sha}",
                source_timestamp=None,
                payload={"tag": tag, "sha": sha, "remote": remote},
            )
        )

    # Cursor is currently unused; dedup is handled via stable source_event_id.
    return CollectResult(events=events, cursor={})
