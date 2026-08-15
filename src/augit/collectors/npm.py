import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def npm_registry_path(package_name: str) -> str:
    """Return the path segment for registry.npmjs.org/{path}."""
    if package_name.startswith("@"):
        scope, pkg = package_name.split("/", 1)
        return f"{urllib.parse.quote(scope, safe='')}/{urllib.parse.quote(pkg, safe='')}"
    return urllib.parse.quote(package_name, safe="")


def npm_release_to_event(
    pkg_name: str,
    version: str,
    *,
    publish_time: str | None,
    maintainers: list[str] | None = None,
    publisher: str | None = None,
    repository_url: str | None = None,
) -> EventIn:
    payload = {
        "name": pkg_name,
        "version": version,
        "publish_time": publish_time,
        "maintainers": maintainers or [],
        "uploaders": maintainers or [],
        "author_login": publisher,
        "repository_url": repository_url,
    }
    return EventIn(
        repo=RepoKey(canonical_url=pkg_name, provider="npm"),
        category="release",
        event_type="npm_release_version",
        source="registry",
        source_event_id=f"npm:{pkg_name}:{version}",
        source_timestamp=_dt(publish_time),
        payload=payload,
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def fetch_npm_json(name: str) -> dict[str, Any]:
    path = npm_registry_path(name)
    url = f"https://registry.npmjs.org/{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "augit")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"_augit_missing": True, "name": name}
        raise


def _version_publisher(version_info: dict[str, Any]) -> str | None:
    npm_user = version_info.get("_npmUser") or {}
    name = npm_user.get("name")
    if name:
        return str(name)
    return None


def _maintainer_names(data: dict[str, Any], version_info: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for maintainer in (data.get("maintainers") or []) + (version_info.get("maintainers") or []):
        if isinstance(maintainer, dict) and maintainer.get("name"):
            names.add(str(maintainer["name"]))
    publisher = _version_publisher(version_info)
    if publisher:
        names.add(publisher)
    return sorted(names)


def _repository_url(data: dict[str, Any], version_info: dict[str, Any]) -> str | None:
    repo = version_info.get("repository") or data.get("repository")
    if isinstance(repo, dict):
        url = repo.get("url")
        return str(url) if url else None
    if isinstance(repo, str):
        return repo
    return None


def collect_npm_versions(
    *,
    package_name: str,
    cursor: dict[str, Any] | None,
    npm_json: dict[str, Any] | None = None,
) -> CollectResult:
    data = npm_json or fetch_npm_json(package_name)
    missing = bool(data.get("_augit_missing"))
    canonical_name = str(data.get("name") or package_name)
    versions_map = data.get("versions") or {}
    time_map = data.get("time") or {}

    prev_versions = set((cursor or {}).get("versions", []))
    versions = sorted(v for v in versions_map if v not in {"created", "modified"})

    events: list[EventIn] = []
    if missing:
        events.append(
            EventIn(
                repo=RepoKey(canonical_url=package_name, provider="npm"),
                category="release",
                event_type="npm_package_missing",
                source="registry",
                source_event_id=f"npm-missing:{package_name}",
                source_timestamp=None,
                payload={
                    "name": package_name,
                    "url": f"https://registry.npmjs.org/{npm_registry_path(package_name)}",
                    "http_status": 404,
                },
            )
        )
        return CollectResult(events=events, cursor={"versions": []})

    with item_progress(f"npm:{canonical_name}", len(versions)) as progress:
        for version in versions:
            if version in prev_versions:
                progress.update(1)
                continue
            version_info = versions_map.get(version) or {}
            publish_time = time_map.get(version)
            events.append(
                npm_release_to_event(
                    canonical_name,
                    version,
                    publish_time=publish_time,
                    maintainers=_maintainer_names(data, version_info),
                    publisher=_version_publisher(version_info),
                    repository_url=_repository_url(data, version_info),
                )
            )
            progress.update(1)

    return CollectResult(events=events, cursor={"versions": versions})
