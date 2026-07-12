"""Collect dependency manifest changes from merged pull requests."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.collectors.github_api import GitHubClient, github_owner_repo, parse_owner_repo
from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey

MANIFEST_FILES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pom.xml",
        "requirements.txt",
        "pyproject.toml",
    }
)
MAX_MERGED_PRS = 20


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
            deps.update(section.keys())
    return deps


def _parse_requirements(content: str) -> set[str]:
    deps: set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
        if name:
            deps.add(name)
    return deps


def _deps_from_file(filename: str, content: str) -> set[str]:
    base = filename.rsplit("/", 1)[-1]
    if base == "package.json":
        return _parse_package_json_deps(content)
    if base == "requirements.txt":
        return _parse_requirements(content)
    return set()


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def collect_dependency_changes(
    client: GitHubClient,
    *,
    repo_key: RepoKey,
    cursor: dict[str, Any] | None,
    merged_prs: list[dict[str, Any]] | None = None,
) -> CollectResult:
    owner_repo = github_owner_repo(repo_key)
    owner, repo = parse_owner_repo(owner_repo)
    processed = set((cursor or {}).get("processed_prs") or [])
    events: list[EventIn] = []
    new_processed = set(processed)

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
            return CollectResult(events=[], cursor={"processed_prs": sorted(processed)})
        pr_list = prs

    merged = [p for p in pr_list if p.get("merged_at")][:MAX_MERGED_PRS]
    with item_progress("dependency PRs", len(merged)) as progress:
        for pr in merged:
            number = int(pr["number"])
            key = f"pr:{number}"
            if key in processed:
                progress.update(1)
                continue
            new_processed.add(key)
            files, _ = client.get_json(f"/repos/{owner}/{repo}/pulls/{number}/files")
            if not isinstance(files, list):
                progress.update(1)
                continue
            for f in files:
                filename = f.get("filename") or ""
                base = filename.rsplit("/", 1)[-1]
                if base not in MANIFEST_FILES:
                    continue
                patch = f.get("patch") or ""
                if not patch:
                    continue
                before, after = _extract_patch_deps(base, patch)
                added = sorted(after - before)
                removed = sorted(before - after)
                if not added and not removed:
                    continue
                payload = {
                    "pr_number": number,
                    "commit_sha": pr.get("merge_commit_sha"),
                    "author_login": (pr.get("user") or {}).get("login"),
                    "manifest": filename,
                    "added": added,
                    "removed": removed,
                }
                events.append(
                    EventIn(
                        repo=repo_key,
                        category="dependency",
                        event_type="dependency_manifest_change",
                        source="github_api",
                        source_event_id=f"dep:{owner_repo}:pr{number}:{filename}",
                        source_timestamp=_dt(pr.get("merged_at")),
                        payload=payload,
                    )
                )
            progress.update(1)

    return CollectResult(
        events=events,
        cursor={"processed_prs": sorted(new_processed)},
    )


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
