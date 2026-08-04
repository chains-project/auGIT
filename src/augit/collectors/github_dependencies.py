"""Collect dependency manifest changes from merged PRs and commits."""

from __future__ import annotations

import base64
import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.collectors.github_api import (
    GitHubApiError,
    GitHubClient,
    github_owner_repo,
    parse_owner_repo,
)
from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey

# Files we look for on PR diffs / commit file lists.
MANIFEST_FILES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pom.xml",
        "requirements.txt",
        "pyproject.toml",
    }
)

# Basename → parse for direct dependency edges (skip lockfiles).
EDGE_MANIFEST_FILES = frozenset(
    {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "pom.xml",
    }
)

# GitHub commits?path= filters for commit-based collection.
MANIFEST_PATHS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "pom.xml",
)

MAX_MERGED_PRS = 20
MAX_MANIFEST_COMMITS = 50
_PEP508_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _parse_package_json_deps(content: str) -> set[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return set()
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key) or {}
        if isinstance(section, dict):
            deps.update(str(name) for name in section.keys())
    return deps


def _parse_requirements(content: str) -> set[str]:
    deps: set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _PEP508_NAME.match(line)
        if match:
            deps.add(match.group(1))
    return deps


def _pep508_name(spec: str) -> str | None:
    spec = spec.strip().strip("\"'")
    if not spec or spec.startswith("#"):
        return None
    match = _PEP508_NAME.match(spec)
    return match.group(1) if match else None


def _parse_pyproject_deps(content: str) -> set[str]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return set()

    deps: set[str] = set()
    project = data.get("project") or {}
    for item in project.get("dependencies") or []:
        if isinstance(item, str):
            name = _pep508_name(item)
            if name:
                deps.add(name)

    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group in optional.values():
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, str):
                    name = _pep508_name(item)
                    if name:
                        deps.add(name)

    poetry_deps = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies")
    if isinstance(poetry_deps, dict):
        for name in poetry_deps:
            if str(name).lower() == "python":
                continue
            deps.add(str(name))

    return deps


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_pom_deps(content: str) -> set[str]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return set()

    deps: set[str] = set()
    for el in root.iter():
        if _local_tag(el.tag) != "dependency":
            continue
        group_id = None
        artifact_id = None
        for child in list(el):
            local = _local_tag(child.tag)
            text = (child.text or "").strip()
            if local == "groupId":
                group_id = text
            elif local == "artifactId":
                artifact_id = text
        if group_id and artifact_id:
            deps.add(f"{group_id}:{artifact_id}")
    return deps


def _deps_from_file(filename: str, content: str) -> set[str]:
    base = filename.rsplit("/", 1)[-1]
    if base == "package.json":
        return _parse_package_json_deps(content)
    if base == "requirements.txt":
        return _parse_requirements(content)
    if base == "pyproject.toml":
        return _parse_pyproject_deps(content)
    if base == "pom.xml":
        return _parse_pom_deps(content)
    return set()


def _extract_patch_deps(base: str, patch: str) -> tuple[set[str], set[str]]:
    before_lines: list[str] = []
    after_lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            after_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            before_lines.append(line[1:])
        elif not line.startswith("@@"):
            before_lines.append(line)
            after_lines.append(line)
    before = _deps_from_file(base, "\n".join(before_lines))
    after = _deps_from_file(base, "\n".join(after_lines))
    return before, after


def _file_content_at_ref(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> str | None:
    """Return decoded file text at ref, or None if missing / not a file."""
    try:
        data, _ = client.get_json(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
    except GitHubApiError:
        return None
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if data.get("encoding") != "base64" or not isinstance(content, str):
        return None
    raw = base64.b64decode(content.replace("\n", ""))
    return raw.decode("utf-8", errors="replace")


def _deps_diff_at_refs(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    path: str,
    before_ref: str | None,
    after_ref: str | None,
) -> tuple[set[str], set[str]]:
    """Compare parsed direct deps for a manifest at two git refs."""
    before_text = (
        _file_content_at_ref(
            client, owner=owner, repo=repo, path=path, ref=before_ref
        )
        if before_ref
        else None
    )
    after_text = (
        _file_content_at_ref(
            client, owner=owner, repo=repo, path=path, ref=after_ref
        )
        if after_ref
        else None
    )
    return (
        _deps_from_file(path, before_text or ""),
        _deps_from_file(path, after_text or ""),
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def _manifest_event(
    *,
    repo_key: RepoKey,
    owner_repo: str,
    source_event_id: str,
    source_timestamp: datetime | None,
    payload: dict[str, Any],
) -> EventIn:
    return EventIn(
        repo=repo_key,
        category="dependency",
        event_type="dependency_manifest_change",
        source="github_api",
        source_event_id=source_event_id,
        source_timestamp=source_timestamp,
        payload=payload,
    )


def _collect_from_prs(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    owner: str,
    repo: str,
    owner_repo: str,
    processed_prs: set[str],
    merged_prs: list[dict[str, Any]] | None,
) -> tuple[list[EventIn], set[str]]:
    events: list[EventIn] = []
    new_processed = set(processed_prs)

    if merged_prs is not None:
        pr_list = merged_prs
    else:
        prs, _ = client.get_json(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": 50,
            },
        )
        if not isinstance(prs, list):
            return events, new_processed
        pr_list = prs

    merged = [p for p in pr_list if p.get("merged_at")][:MAX_MERGED_PRS]
    with item_progress("dependency PRs", len(merged)) as progress:
        for pr in merged:
            number = int(pr["number"])
            key = f"pr:{number}"
            if key in processed_prs:
                progress.update(1)
                continue
            new_processed.add(key)
            files, _ = client.get_json(f"/repos/{owner}/{repo}/pulls/{number}/files")
            if not isinstance(files, list):
                progress.update(1)
                continue

            merge_sha = pr.get("merge_commit_sha")
            parent_sha: str | None = None
            if merge_sha:
                try:
                    detail, _ = client.get_json(
                        f"/repos/{owner}/{repo}/commits/{merge_sha}"
                    )
                except GitHubApiError:
                    detail = None
                if isinstance(detail, dict):
                    parents = detail.get("parents") or []
                    if parents:
                        parent_sha = parents[0].get("sha")

            for f in files:
                filename = f.get("filename") or ""
                base = filename.rsplit("/", 1)[-1]
                if base not in EDGE_MANIFEST_FILES:
                    continue
                before: set[str] = set()
                after: set[str] = set()
                if merge_sha:
                    before, after = _deps_diff_at_refs(
                        client,
                        owner=owner,
                        repo=repo,
                        path=filename,
                        before_ref=parent_sha,
                        after_ref=merge_sha,
                    )
                if not before and not after:
                    patch = f.get("patch") or ""
                    if patch:
                        before, after = _extract_patch_deps(base, patch)
                added = sorted(after - before)
                removed = sorted(before - after)
                if not added and not removed:
                    continue
                events.append(
                    _manifest_event(
                        repo_key=repo_key,
                        owner_repo=owner_repo,
                        source_event_id=f"dep:{owner_repo}:pr{number}:{filename}",
                        source_timestamp=_dt(pr.get("merged_at")),
                        payload={
                            "pr_number": number,
                            "commit_sha": merge_sha,
                            "author_login": (pr.get("user") or {}).get("login"),
                            "manifest": filename,
                            "added": added,
                            "removed": removed,
                        },
                    )
                )
            progress.update(1)

    return events, new_processed


def _list_manifest_commit_shas(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    since: str | None,
) -> list[str]:
    """Newest-first unique SHAs for commits that touch ecosystem manifests."""
    seen: set[str] = set()
    ordered: list[str] = []
    for path in MANIFEST_PATHS:
        params: dict[str, Any] = {"path": path, "per_page": 100}
        if since:
            params["since"] = since
        pages = 0
        for page_data in client.paginate(
            f"/repos/{owner}/{repo}/commits", params=params
        ):
            pages += 1
            if pages > 3:
                break
            if not isinstance(page_data, list):
                break
            for commit in page_data:
                sha = commit.get("sha")
                if not sha or sha in seen:
                    continue
                seen.add(sha)
                ordered.append(sha)
                if len(ordered) >= MAX_MANIFEST_COMMITS:
                    return ordered
    return ordered


def _collect_from_commits(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    owner: str,
    repo: str,
    owner_repo: str,
    processed_commits: set[str],
    since: str | None,
) -> tuple[list[EventIn], set[str], str | None]:
    events: list[EventIn] = []
    new_processed = set(processed_commits)
    newest_ts = since

    shas = _list_manifest_commit_shas(
        client, owner=owner, repo=repo, since=since
    )
    to_fetch = [sha for sha in shas if sha not in processed_commits]

    with item_progress("dependency commits", len(to_fetch)) as progress:
        for sha in to_fetch:
            new_processed.add(sha)
            detail, _ = client.get_json(f"/repos/{owner}/{repo}/commits/{sha}")
            if not isinstance(detail, dict):
                progress.update(1)
                continue

            commit_obj = detail.get("commit") or {}
            committer = commit_obj.get("committer") or {}
            author_obj = commit_obj.get("author") or {}
            ts_raw = committer.get("date") or author_obj.get("date")
            if ts_raw and (newest_ts is None or ts_raw > newest_ts):
                newest_ts = ts_raw

            author_login = (detail.get("author") or {}).get("login") or (
                detail.get("committer") or {}
            ).get("login")

            files = detail.get("files") or []
            if not isinstance(files, list):
                progress.update(1)
                continue

            parents = detail.get("parents") or []
            parent_sha = parents[0].get("sha") if parents else None

            for f in files:
                filename = f.get("filename") or ""
                base = filename.rsplit("/", 1)[-1]
                if base not in EDGE_MANIFEST_FILES:
                    continue
                # Full file at parent vs commit — GitHub patches are often partial
                # hunks that do not reconstruct to valid package.json / pom.xml.
                before, after = _deps_diff_at_refs(
                    client,
                    owner=owner,
                    repo=repo,
                    path=filename,
                    before_ref=parent_sha,
                    after_ref=sha,
                )
                added = sorted(after - before)
                removed = sorted(before - after)
                if not added and not removed:
                    continue
                events.append(
                    _manifest_event(
                        repo_key=repo_key,
                        owner_repo=owner_repo,
                        source_event_id=f"dep:{owner_repo}:commit:{sha}:{filename}",
                        source_timestamp=_dt(ts_raw),
                        payload={
                            "pr_number": None,
                            "commit_sha": sha,
                            "author_login": author_login,
                            "manifest": filename,
                            "added": added,
                            "removed": removed,
                        },
                    )
                )
            progress.update(1)

    return events, new_processed, newest_ts


def collect_dependency_changes(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    merged_prs: list[dict[str, Any]] | None = None,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    processed_prs = set((cursor or {}).get("processed_prs") or [])
    processed_commits = set((cursor or {}).get("processed_commits") or [])
    since = (cursor or {}).get("since")

    pr_events, new_prs = _collect_from_prs(
        client,
        repo_key=repo_key,
        owner=owner,
        repo=repo,
        owner_repo=owner_repo,
        processed_prs=processed_prs,
        merged_prs=merged_prs,
    )
    commit_events, new_commits, newest_ts = _collect_from_commits(
        client,
        repo_key=repo_key,
        owner=owner,
        repo=repo,
        owner_repo=owner_repo,
        processed_commits=processed_commits,
        since=since,
    )

    return CollectResult(
        events=pr_events + commit_events,
        cursor={
            "processed_prs": sorted(new_prs),
            "processed_commits": sorted(new_commits),
            "since": newest_ts or since,
        },
    )
