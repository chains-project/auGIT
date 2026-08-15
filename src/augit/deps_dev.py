"""Minimal deps.dev client for GitHub → package reverse lookup."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from augit.collectors.github_api import github_owner_repo
from augit.models import RepoKey

DEPS_DEV_BASE = "https://api.deps.dev/v3"


@dataclass(frozen=True)
class DepsDevPackage:
    system: str  # PYPI | MAVEN | NPM | ...
    name: str  # PyPI name or Maven group:artifact


def fetch_project_package_versions(github_key: RepoKey) -> list[DepsDevPackage]:
    """
    Return package coordinates known to deps.dev for a GitHub project.

    Uses ``GET /v3/projects/{id}:packageversions``. Failures return [].
    """
    slug = github_owner_repo(github_key)
    project_id = f"github.com/{slug}"
    path = urllib.parse.quote(project_id, safe="")
    url = f"{DEPS_DEV_BASE}/projects/{path}:packageversions"
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "augit")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []

    out: list[DepsDevPackage] = []
    seen: set[tuple[str, str]] = set()
    for row in data.get("versions") or []:
        vk = row.get("versionKey") or {}
        system = (vk.get("system") or "").upper()
        name = vk.get("name") or ""
        if system not in {"PYPI", "MAVEN", "NPM"} or not name:
            continue
        key = (system, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(DepsDevPackage(system=system, name=name))
    return out
