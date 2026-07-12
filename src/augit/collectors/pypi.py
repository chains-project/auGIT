import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def pypi_release_to_event(
    pkg_name: str,
    version: str,
    info: dict[str, Any],
    upload_time: str | None,
    *,
    uploaders: list[str] | None = None,
) -> EventIn:
    payload = {
        "name": pkg_name,
        "version": version,
        "project_url": info.get("project_url") or info.get("package_url"),
        "home_page": info.get("home_page"),
        "project_urls": info.get("project_urls"),
        "upload_time": upload_time,
        "requires_python": info.get("requires_python"),
        "uploaders": uploaders or [],
        "author_login": info.get("author"),
    }
    return EventIn(
        repo=RepoKey(canonical_url=pkg_name, provider="pypi"),
        category="release",
        event_type="pypi_release_version",
        source="registry",
        source_event_id=f"pypi:{pkg_name}:{version}",
        source_timestamp=_dt(upload_time),
        payload=payload,
    )


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def fetch_pypi_json(name: str) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{name}/json"
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "augit")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Some incident-case projects (e.g. ctx) are removed and name-blocked by PyPI
        # admins, which returns 404 for the JSON endpoint. Treat this as "no data".
        if e.code == 404:
            return {"_augit_missing": True, "info": {"name": name}, "releases": {}}
        raise


def collect_pypi_versions(
    *,
    package_name: str,
    cursor: dict[str, Any] | None,
    pypi_json: dict[str, Any] | None = None,
) -> CollectResult:
    data = pypi_json or fetch_pypi_json(package_name)
    info = data.get("info") or {}
    releases = data.get("releases") or {}
    missing = bool(data.get("_augit_missing"))

    # Cursor: remember a simple hash of known versions (helps skip work).
    prev_versions = set((cursor or {}).get("versions", []))
    versions = sorted(releases.keys())

    events: list[EventIn] = []
    if missing:
        events.append(
            EventIn(
                repo=RepoKey(canonical_url=package_name, provider="pypi"),
                category="release",
                event_type="pypi_project_missing",
                source="registry",
                source_event_id=f"pypi-missing:{package_name}",
                source_timestamp=None,
                payload={
                    "name": package_name,
                    "url": f"https://pypi.org/pypi/{package_name}/json",
                    "http_status": 404,
                },
            )
        )
    with item_progress(f"pypi:{package_name}", len(versions)) as progress:
        for v in versions:
            if v in prev_versions:
                progress.update(1)
                continue
            files = releases.get(v) or []
            upload_time = None
            uploaders: list[str] = []
            if files:
                times = [
                    f.get("upload_time_iso_8601")
                    for f in files
                    if f.get("upload_time_iso_8601")
                ]
                upload_time = sorted(times)[0] if times else None
                uploaders = sorted(
                    {f.get("uploaded_by") for f in files if f.get("uploaded_by")}
                )
            events.append(
                pypi_release_to_event(
                    package_name, v, info, upload_time, uploaders=uploaders
                )
            )
            progress.update(1)

    return CollectResult(events=events, cursor={"versions": versions})
