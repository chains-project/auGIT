"""Repository profile and audit context for trust-report analysis."""

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from augit.analysis.timeline import RepoTimeline, event_timestamp, parse_dt
from augit.signing import normalize_signing_key_id

DEFAULT_TAIL_DAYS = 90
SHORT_PRIVILEGE_DAYS = 14


class IntegrationMode(str, Enum):
    PR_REVIEWED = "pr_reviewed"
    DIRECT_PUSH_OK = "direct_push_ok"
    MIXED = "mixed"


class SigningProfile(BaseModel):
    ever_signed: bool = False
    key_ids: list[str] = Field(default_factory=list)


class PrReviewProfile(BaseModel):
    median_review_comments: float = 0.0
    median_reviews: float = 0.0
    merged_pr_count: int = 0


class ReleaseBaseline(BaseModel):
    median_inter_release_days: float | None = None
    typical_version_prefix: str | None = None
    tag_aligned_releases: bool = True


class RepositoryProfile(BaseModel):
    privileged_mergers: set[str] = Field(default_factory=set)
    privileged_releasers: set[str] = Field(default_factory=set)
    merged_pr_authors: set[str] = Field(default_factory=set)
    first_contribution_at: dict[str, datetime] = Field(default_factory=dict)
    first_privilege_at: dict[str, datetime] = Field(default_factory=dict)
    signing_by_login: dict[str, SigningProfile] = Field(default_factory=dict)
    pr_review: PrReviewProfile = Field(default_factory=PrReviewProfile)
    integration_mode: IntegrationMode = IntegrationMode.MIXED
    pr_merge_shas: set[str] = Field(default_factory=set)
    release_baseline: ReleaseBaseline = Field(default_factory=ReleaseBaseline)
    release_publishers_github: set[str] = Field(default_factory=set)
    release_publishers_registry: set[str] = Field(default_factory=set)
    dependency_edges: set[str] = Field(default_factory=set)
    profile_built_until: datetime | None = None
    frozen: bool = False

    model_config = {"arbitrary_types_allowed": True}

    def model_dump_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), default=_json_default)

    @classmethod
    def from_json(cls, data: str) -> RepositoryProfile:
        raw = json.loads(data)
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "privileged_mergers": sorted(self.privileged_mergers),
            "privileged_releasers": sorted(self.privileged_releasers),
            "merged_pr_authors": sorted(self.merged_pr_authors),
            "first_contribution_at": {
                k: v.isoformat() for k, v in self.first_contribution_at.items()
            },
            "first_privilege_at": {
                k: v.isoformat() for k, v in self.first_privilege_at.items()
            },
            "signing_by_login": {
                k: v.model_dump() for k, v in self.signing_by_login.items()
            },
            "pr_review": self.pr_review.model_dump(),
            "integration_mode": self.integration_mode.value,
            "pr_merge_shas": sorted(self.pr_merge_shas),
            "release_baseline": self.release_baseline.model_dump(),
            "release_publishers_github": sorted(self.release_publishers_github),
            "release_publishers_registry": sorted(self.release_publishers_registry),
            "dependency_edges": sorted(self.dependency_edges),
            "profile_built_until": (
                self.profile_built_until.isoformat()
                if self.profile_built_until
                else None
            ),
            "frozen": self.frozen,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RepositoryProfile:
        return cls(
            privileged_mergers=set(raw.get("privileged_mergers") or []),
            privileged_releasers=set(raw.get("privileged_releasers") or []),
            merged_pr_authors=set(raw.get("merged_pr_authors") or []),
            first_contribution_at={
                k: parse_dt(v) or datetime.min.replace(tzinfo=UTC)
                for k, v in (raw.get("first_contribution_at") or {}).items()
            },
            first_privilege_at={
                k: parse_dt(v) or datetime.min.replace(tzinfo=UTC)
                for k, v in (raw.get("first_privilege_at") or {}).items()
            },
            signing_by_login={
                k: SigningProfile(**v)
                for k, v in (raw.get("signing_by_login") or {}).items()
            },
            pr_review=PrReviewProfile(**(raw.get("pr_review") or {})),
            integration_mode=IntegrationMode(raw.get("integration_mode", "mixed")),
            pr_merge_shas=set(raw.get("pr_merge_shas") or []),
            release_baseline=ReleaseBaseline(**(raw.get("release_baseline") or {})),
            release_publishers_github=set(raw.get("release_publishers_github") or []),
            release_publishers_registry=set(
                raw.get("release_publishers_registry") or []
            ),
            dependency_edges=set(raw.get("dependency_edges") or []),
            profile_built_until=parse_dt(raw.get("profile_built_until")),
            frozen=bool(raw.get("frozen")),
        )


def _median_review_metric(values: list[float]) -> float:
    """Median review depth; when most PRs store 0, use nonzero sample if large enough."""
    if not values:
        return 0.0
    overall = statistics.median(values)
    if overall > 0:
        return float(overall)
    nonzero = [v for v in values if v > 0]
    if len(nonzero) >= 5:
        return float(statistics.median(nonzero))
    return 0.0


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


AuditMode = Literal["initial", "reaudit"]


@dataclass(frozen=True)
class AuditContext:
    mode: AuditMode
    compare_start: datetime
    compare_end: datetime
    baseline_profile: RepositoryProfile
    checkpoint_at: datetime | None = None
    tail_days: int = DEFAULT_TAIL_DAYS


def _has_integrity_freeze(
    timeline: RepoTimeline, compare_start: datetime, compare_end: datetime
) -> bool:
    for ev in timeline.integrity_events:
        ts = ev.get("event_ts")
        if ts is None or ts < compare_start or ts > compare_end:
            continue
        subtype = ev.get("subtype") or ""
        severity = ev.get("severity") or "low"
        if subtype in ("commit_missing", "tag_retargeted") and severity == "high":
            return True
    return False


def build_profile(
    timeline: RepoTimeline,
    *,
    baseline_until: datetime,
    compare_start: datetime | None = None,
    compare_end: datetime | None = None,
) -> RepositoryProfile:
    profile = RepositoryProfile(profile_built_until=baseline_until)

    if (
        compare_start
        and compare_end
        and _has_integrity_freeze(timeline, compare_start, compare_end)
    ):
        profile.frozen = True
        return profile

    baseline_merged = [
        p
        for p in timeline.merged_prs
        if p.get("merged_dt") and p["merged_dt"] < baseline_until
    ]
    baseline_closed = [
        p
        for p in timeline.closed_prs
        if p.get("event_ts") and p["event_ts"] < baseline_until
    ]
    baseline_commits = [
        c
        for c in timeline.commits
        if c.get("event_ts") and c["event_ts"] < baseline_until
    ]
    baseline_releases = [
        r
        for r in timeline.releases
        if r.get("event_ts") and r["event_ts"] < baseline_until
    ]
    baseline_tags = [
        t for t in timeline.tags if t.get("event_ts") and t["event_ts"] < baseline_until
    ]
    baseline_registry = [
        r
        for r in timeline.registry_versions
        if r.get("event_ts") and r["event_ts"] < baseline_until
    ]
    baseline_deps = [
        d
        for d in timeline.dependency_changes
        if d.get("event_ts") and d["event_ts"] < baseline_until
    ]

    for pr in baseline_merged:
        author = pr.get("author_login")
        if author:
            profile.merged_pr_authors.add(author)
        merger = pr.get("merged_by_login")
        merged_dt = pr.get("merged_dt")
        if merger and merged_dt:
            profile.privileged_mergers.add(merger)
            _update_first(profile.first_contribution_at, merger, merged_dt)
            _update_first(profile.first_privilege_at, merger, merged_dt)
        sha = pr.get("merge_commit_sha")
        if sha:
            profile.pr_merge_shas.add(sha)

    for rel in baseline_releases:
        author = rel.get("author_login")
        dt = rel.get("published_dt")
        if author and dt:
            profile.privileged_releasers.add(author)
            profile.release_publishers_github.add(author)
            _update_first(profile.first_contribution_at, author, dt)
            _update_first(profile.first_privilege_at, author, dt)

    for commit in baseline_commits:
        author = commit.get("author_login")
        dt = commit.get("committed_dt")
        if author and dt:
            _update_first(profile.first_contribution_at, author, dt)
        _update_signing(profile, commit)

    review_comments: list[float] = []
    review_counts: list[float] = []
    for pr in baseline_merged:
        rc = pr.get("review_comment_count")
        rv = pr.get("review_count")
        if rc is not None:
            review_comments.append(float(rc))
        if rv is not None:
            review_counts.append(float(rv))

    accepted = sum(1 for pr in baseline_closed if pr.get("merged_at"))
    profile.pr_review = PrReviewProfile(
        median_review_comments=_median_review_metric(review_comments),
        median_reviews=_median_review_metric(review_counts),
        merged_pr_count=accepted,
    )

    pr_linked = 0
    direct = 0
    for commit in baseline_commits:
        sha = commit.get("sha")
        if sha and sha in profile.pr_merge_shas:
            pr_linked += 1
        else:
            direct += 1
    if pr_linked > 0 and direct == 0:
        profile.integration_mode = IntegrationMode.PR_REVIEWED
    elif direct > 0 and pr_linked == 0:
        profile.integration_mode = IntegrationMode.DIRECT_PUSH_OK
    elif pr_linked > 0 and direct > 0:
        ratio = pr_linked / (pr_linked + direct)
        profile.integration_mode = (
            IntegrationMode.PR_REVIEWED if ratio >= 0.7 else IntegrationMode.MIXED
        )

    release_dates = sorted(
        r["published_dt"] for r in baseline_releases if r.get("published_dt")
    )
    if len(release_dates) >= 2:
        gaps = [
            (release_dates[i] - release_dates[i - 1]).days
            for i in range(1, len(release_dates))
        ]
        profile.release_baseline.median_inter_release_days = float(
            statistics.median(gaps)
        )

    tag_by_name = {
        t["tag_name"]: t.get("sha") for t in baseline_tags if t.get("tag_name")
    }
    aligned = 0
    for rel in baseline_releases:
        tag = rel.get("tag_name")
        dt = rel.get("published_dt")
        if tag and tag in tag_by_name and dt:
            aligned += 1
    profile.release_baseline.tag_aligned_releases = aligned > 0 or not baseline_releases

    if baseline_releases:
        sample = baseline_releases[0].get("tag_name") or ""
        profile.release_baseline.typical_version_prefix = _version_prefix(sample)

    for reg in baseline_registry:
        for uploader in reg.get("uploaders") or []:
            profile.release_publishers_registry.add(str(uploader))
        author = reg.get("author_login")
        if author:
            profile.release_publishers_registry.add(author)

    for dep in baseline_deps:
        for edge in dep.get("added") or []:
            profile.dependency_edges.add(str(edge))

    return profile


def _update_first(store: dict[str, datetime], login: str, dt: datetime) -> None:
    prev = store.get(login)
    if prev is None or dt < prev:
        store[login] = dt


def _update_signing(profile: RepositoryProfile, commit: dict[str, Any]) -> None:
    author = commit.get("author_login")
    if not author:
        return
    key_id = normalize_signing_key_id(commit.get("signer_key_id"))
    if not commit.get("verified") or not key_id:
        return
    entry = profile.signing_by_login.setdefault(author, SigningProfile())
    entry.ever_signed = True
    if key_id not in entry.key_ids:
        entry.key_ids.append(key_id)


def _version_prefix(tag: str) -> str:
    for i, ch in enumerate(tag):
        if ch.isdigit():
            return tag[:i]
    return ""


def resolve_audit_context(
    *,
    mode: AuditMode,
    timeline: RepoTimeline,
    tail_days: int = DEFAULT_TAIL_DAYS,
    as_of: datetime | None = None,
    stored_profile: RepositoryProfile | None = None,
    checkpoint_at: datetime | None = None,
) -> AuditContext:
    compare_end = as_of or timeline.last_event_at or datetime.now(UTC)
    if compare_end.tzinfo is None:
        compare_end = compare_end.replace(tzinfo=UTC)

    if mode == "reaudit":
        if stored_profile is None or checkpoint_at is None:
            raise ValueError("re-audit mode requires a stored profile and checkpoint")
        return AuditContext(
            mode=mode,
            compare_start=checkpoint_at,
            compare_end=compare_end,
            baseline_profile=stored_profile,
            checkpoint_at=checkpoint_at,
            tail_days=tail_days,
        )

    compare_start = compare_end - timedelta(days=tail_days)
    baseline_profile = build_profile(
        timeline,
        baseline_until=compare_start,
        compare_start=compare_start,
        compare_end=compare_end,
    )
    return AuditContext(
        mode=mode,
        compare_start=compare_start,
        compare_end=compare_end,
        baseline_profile=baseline_profile,
        tail_days=tail_days,
    )


def rows_for_profile(
    rows: list[dict[str, Any]], baseline_until: datetime
) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if (event_timestamp(r) or datetime.min.replace(tzinfo=UTC))
        < baseline_until
    ]
