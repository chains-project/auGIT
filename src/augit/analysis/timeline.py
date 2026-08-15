"""Parse audit-log rows into a structured timeline for analysis."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def event_timestamp(row: dict[str, Any]) -> datetime | None:
    return parse_dt(row.get("source_timestamp")) or parse_dt(row.get("observed_at"))


@dataclass
class RepoTimeline:
    """Parsed events used by profile building and detectors."""

    integrity_events: list[dict[str, Any]] = field(default_factory=list)
    merged_prs: list[dict[str, Any]] = field(default_factory=list)
    closed_prs: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    releases: list[dict[str, Any]] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    registry_versions: list[dict[str, Any]] = field(default_factory=list)
    registry_missing: list[dict[str, Any]] = field(default_factory=list)
    dependency_changes: list[dict[str, Any]] = field(default_factory=list)
    first_collect_at: datetime | None = None
    last_event_at: datetime | None = None
    total_events: int = 0


def load_timeline(rows: list[dict[str, Any]]) -> RepoTimeline:
    timeline = RepoTimeline()
    observed: list[datetime] = []

    for row in rows:
        timeline.total_events += 1
        et = row["event_type"]
        payload = row["payload"] or {}
        obs = parse_dt(row.get("observed_at"))
        # Integrity drift events (from `check` runs) should not move collection coverage.
        # They are still present in the timeline for integrity metrics.
        if obs and row.get("source") != "refetch_compare":
            observed.append(obs)
        ts = event_timestamp(row)

        if et == "integrity_drift":
            timeline.integrity_events.append(
                {
                    "observed_at": row["observed_at"],
                    "event_ts": ts,
                    "subtype": payload.get("subtype"),
                    "severity": payload.get("severity"),
                    "expected": payload.get("expected"),
                    "observed": payload.get("observed"),
                }
            )
        elif et == "github_pull_request":
            pr = {
                "number": payload.get("number"),
                "state": payload.get("state"),
                "author_login": payload.get("author_login"),
                "merged_at": payload.get("merged_at"),
                "merged_dt": parse_dt(payload.get("merged_at")),
                "merge_commit_sha": payload.get("merge_commit_sha"),
                "base_branch": payload.get("base_branch"),
                "review_comment_count": payload.get("review_comment_count"),
                "review_count": payload.get("review_count"),
                "review_states": payload.get("review_states") or [],
                "merged_by_login": payload.get("merged_by_login"),
                "event_ts": ts,
            }
            if payload.get("merged_at"):
                timeline.merged_prs.append(pr)
            if payload.get("state") == "closed":
                timeline.closed_prs.append(pr)
        elif et == "github_commit":
            timeline.commits.append(
                {
                    "sha": payload.get("sha"),
                    "author_login": payload.get("author_login")
                    or payload.get("committer_login"),
                    "committer_login": payload.get("committer_login"),
                    "verified": payload.get("verified"),
                    "verification_reason": payload.get("verification_reason"),
                    "signer_key_id": payload.get("signer_key_id"),
                    "parents_count": payload.get("parents_count"),
                    "observed_at": row["observed_at"],
                    "committed_dt": ts,
                    "event_ts": ts,
                }
            )
        elif et == "github_release":
            timeline.releases.append(
                {
                    "tag_name": payload.get("tag_name"),
                    "target_commitish": payload.get("target_commitish"),
                    "author_login": payload.get("author_login"),
                    "published_at": payload.get("published_at"),
                    "published_dt": parse_dt(payload.get("published_at")),
                    "event_ts": ts,
                }
            )
        elif et == "github_tag":
            timeline.tags.append(
                {
                    "tag_name": payload.get("tag_name"),
                    "sha": payload.get("sha"),
                    "event_ts": ts,
                }
            )
        elif et in ("pypi_release_version", "maven_release_version", "npm_release_version"):
            registry = "pypi" if et.startswith("pypi") else "maven" if et.startswith("maven") else "npm"
            timeline.registry_versions.append(
                {
                    "version": payload.get("version"),
                    "published_at": payload.get("published_at")
                    or payload.get("upload_time")
                    or payload.get("publish_time"),
                    "published_dt": ts,
                    "author_login": payload.get("author_login"),
                    "uploaders": payload.get("uploaders") or payload.get("maintainers") or [],
                    "registry": registry,
                    "event_ts": ts,
                }
            )
        elif et in ("pypi_project_missing", "npm_package_missing"):
            timeline.registry_missing.append(
                {
                    "registry": "pypi" if et.startswith("pypi") else "npm",
                    "name": payload.get("name"),
                    "url": payload.get("url"),
                    "http_status": payload.get("http_status"),
                    "event_ts": ts,
                }
            )
        elif et == "dependency_manifest_change":
            timeline.dependency_changes.append(
                {
                    "added": payload.get("added") or [],
                    "removed": payload.get("removed") or [],
                    "author_login": payload.get("author_login"),
                    "commit_sha": payload.get("commit_sha"),
                    "pr_number": payload.get("pr_number"),
                    "event_ts": ts,
                }
            )

    if observed:
        timeline.first_collect_at = min(observed)
        timeline.last_event_at = max(observed)

    _min_dt = datetime.min.replace(tzinfo=UTC)

    def _pr_sort_key(pr: dict[str, Any]) -> datetime:
        return pr.get("merged_dt") or pr.get("event_ts") or _min_dt

    timeline.merged_prs.sort(key=_pr_sort_key)
    timeline.closed_prs.sort(key=_pr_sort_key)
    timeline.releases.sort(
        key=lambda p: p.get("published_dt") or p.get("event_ts") or _min_dt
    )
    timeline.commits.sort(
        key=lambda c: c.get("committed_dt") or c.get("event_ts") or _min_dt
    )
    return timeline


def count_events_in_window(
    rows: list[dict[str, Any]],
    *,
    since: datetime,
    until: datetime,
) -> int:
    """Count audit-log rows whose timestamp falls in [since, until]."""
    count = 0
    for row in rows:
        # Don't let integrity drift events distort window counts used for reports.
        if row.get("source") == "refetch_compare":
            continue
        ts = event_timestamp(row)
        if ts is None:
            continue
        if ts < since or ts > until:
            continue
        count += 1
    return count


def filter_timeline_by_window(
    timeline: RepoTimeline,
    *,
    since: datetime | None,
    until: datetime | None,
) -> RepoTimeline:
    """Return a shallow copy containing only events in [since, until].

    ``registry_missing`` is passed through unfiltered: a PyPI 404 reflects
  current registry state and should surface even in retrospective reports.
    """

    def in_window(ts: datetime | None) -> bool:
        if ts is None:
            return since is None and until is None
        if since is not None and ts < since:
            return False
        if until is not None and ts > until:
            return False
        return True

    def filt(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [i for i in items if in_window(i.get("event_ts"))]

    def filt_merged_prs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [i for i in items if in_window(i.get("merged_dt") or i.get("event_ts"))]

    return RepoTimeline(
        integrity_events=filt(timeline.integrity_events),
        merged_prs=filt_merged_prs(timeline.merged_prs),
        closed_prs=filt(timeline.closed_prs),
        commits=filt(timeline.commits),
        releases=filt(timeline.releases),
        tags=filt(timeline.tags),
        registry_versions=filt(timeline.registry_versions),
        registry_missing=list(timeline.registry_missing),
        dependency_changes=filt(timeline.dependency_changes),
        first_collect_at=timeline.first_collect_at,
        last_event_at=timeline.last_event_at,
        total_events=timeline.total_events,
    )
