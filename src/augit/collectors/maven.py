import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from augit.collectors.progress import item_progress
from augit.models import EventIn, RepoKey


def parse_gav(gav: str) -> tuple[str, str]:
    if ":" not in gav:
        raise ValueError("gav must be groupId:artifactId")
    g, a = gav.split(":", 1)
    if not g or not a:
        raise ValueError("gav must be groupId:artifactId")
    return g, a


def _ts_ms_to_dt(ts_ms: int | None) -> datetime | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone()


def maven_version_to_event(
    group_id: str,
    artifact_id: str,
    version: str,
    *,
    timestamp_ms: int | None,
    packaging: str | None,
    scm_url: str | None,
) -> EventIn:
    payload = {
        "group_id": group_id,
        "artifact_id": artifact_id,
        "version": version,
        "packaging": packaging,
        "timestamp": timestamp_ms,
        "scm_url": scm_url,
    }
    return EventIn(
        repo=RepoKey(canonical_url=f"{group_id}:{artifact_id}", provider="maven"),
        category="release",
        event_type="maven_release_version",
        source="registry",
        source_event_id=f"maven:{group_id}:{artifact_id}:{version}",
        source_timestamp=_ts_ms_to_dt(timestamp_ms),
        payload=payload,
    )


def fetch_maven_versions(gav: str, *, rows: int = 200) -> dict[str, Any]:
    g, a = parse_gav(gav)
    q = f'g:"{g}" AND a:"{a}"'
    params = {
        "q": q,
        "rows": rows,
        "wt": "json",
        "core": "gav",
        "fl": "v,timestamp,p,scm",
    }
    url = "https://search.maven.org/solrsearch/select?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "augit")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


@dataclass(frozen=True)
class CollectResult:
    events: list[EventIn]
    cursor: dict[str, Any]


def collect_maven_versions(
    *,
    gav: str,
    cursor: dict[str, Any] | None,
    maven_json: dict[str, Any] | None = None,
) -> CollectResult:
    g, a = parse_gav(gav)
    data = maven_json or fetch_maven_versions(gav)
    response = data.get("response") or {}
    docs = response.get("docs") or []
    num_found = response.get("numFound")
    total = len(docs) if num_found is None else min(int(num_found), len(docs))

    prev_versions = set((cursor or {}).get("versions", []))
    versions: list[str] = []
    events: list[EventIn] = []

    with item_progress(f"maven:{gav}", total) as progress:
        for d in docs:
            v = d.get("v")
            if not v:
                progress.update(1)
                continue
            versions.append(v)
            if v in prev_versions:
                progress.update(1)
                continue
            events.append(
                maven_version_to_event(
                    g,
                    a,
                    v,
                    timestamp_ms=d.get("timestamp"),
                    packaging=d.get("p"),
                    scm_url=d.get("scm"),
                )
            )
            progress.update(1)

    versions_sorted = sorted(set(versions))
    return CollectResult(events=events, cursor={"versions": versions_sorted})
