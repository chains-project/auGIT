from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from augit.analysis.profile import (
    AuditContext,
    RepositoryProfile,
    build_profile,
    resolve_audit_context,
)
from augit.analysis.timeline import count_events_in_window, load_timeline
from augit.analysis.trust_signals import (
    IN_SCOPE_METRICS,
    Finding,
    MetricSpec,
    detect_findings,
    overall_status,
)
from augit.analysis.trust_signals.metrics._helpers import summarize_baseline_by_category
from augit.models import RepoKey
from augit.store import EventStore

AuditMode = Literal["initial", "reaudit"]


@dataclass
class TrustReport:
    repo: RepoKey
    generated_at: datetime
    status: str  # ok | findings
    total_events: int
    coverage_from: datetime | None
    coverage_to: datetime | None
    compare_window_events: int = 0
    findings: list[Finding] = field(default_factory=list)
    metrics_catalog: tuple[MetricSpec, ...] = IN_SCOPE_METRICS
    audit_mode: AuditMode = "initial"
    compare_start: datetime | None = None
    compare_end: datetime | None = None
    checkpoint_at: datetime | None = None
    profile_frozen: bool = False
    tail_days: int = 90
    last_report_at: datetime | None = None
    last_report_status: str | None = None
    last_integrity_refetch_at: datetime | None = None
    last_integrity_summary: dict[str, Any] | None = None
    baseline_by_category: dict[str, list[str]] = field(default_factory=dict)

@dataclass(frozen=True)
class ReportOptions:
    mode: AuditMode = "initial"
    tail_days: int = 90
    as_of: datetime | None = None
    acknowledge: bool = False


def build_trust_report(
    store: EventStore,
    repo: RepoKey,
    *,
    options: ReportOptions | None = None,
) -> TrustReport:
    opts = options or ReportOptions()
    rows = list(store.iter_events_for_repo(repo))
    timeline = load_timeline(rows)
    audit_state = store.get_audit_state(repo)

    stored_profile: RepositoryProfile | None = None
    checkpoint_at: datetime | None = None
    if opts.mode == "reaudit":
        if audit_state is None or not audit_state.profile_json:
            raise ValueError(
                "re-audit mode requires a prior acknowledged checkpoint; "
                "run report with --acknowledge first"
            )
        stored_profile = RepositoryProfile.from_json(audit_state.profile_json)
        checkpoint_at = audit_state.checkpoint_at

    context = resolve_audit_context(
        mode=opts.mode,
        timeline=timeline,
        tail_days=opts.tail_days,
        as_of=opts.as_of,
        stored_profile=stored_profile,
        checkpoint_at=checkpoint_at,
    )
    findings = detect_findings(timeline, context)
    generated_at = datetime.now().astimezone()
    status = overall_status(findings)
    compare_window_events = count_events_in_window(
        rows,
        since=context.compare_start,
        until=context.compare_end,
    )

    prior_report_at = audit_state.last_report_at if audit_state else None
    prior_report_status = audit_state.last_report_status if audit_state else None
    latest_refetch = store.get_latest_integrity_refetch(repo)

    report = TrustReport(
        repo=repo,
        generated_at=generated_at,
        status=status,
        total_events=timeline.total_events,
        compare_window_events=compare_window_events,
        coverage_from=timeline.first_collect_at,
        coverage_to=timeline.last_event_at,
        findings=findings,
        audit_mode=opts.mode,
        compare_start=context.compare_start,
        compare_end=context.compare_end,
        checkpoint_at=context.checkpoint_at,
        profile_frozen=context.baseline_profile.frozen,
        tail_days=opts.tail_days,
        last_report_at=prior_report_at,
        last_report_status=prior_report_status,
        last_integrity_refetch_at=(
            latest_refetch["refetched_at"] if latest_refetch else None
        ),
        last_integrity_summary=(
            latest_refetch["summary"] if latest_refetch else None
        ),
        baseline_by_category=summarize_baseline_by_category(context.baseline_profile),
    )

    store.save_report_meta(repo, report_at=generated_at, status=status)

    if opts.acknowledge:
        snapshot_profile = _snapshot_profile_for_checkpoint(
            timeline, context, stored_profile
        )
        store.save_checkpoint(
            repo,
            checkpoint_at=context.compare_end,
            profile_json=snapshot_profile.model_dump_json(),
            report_status=status,
        )

    return report


def _snapshot_profile_for_checkpoint(
    timeline: Any,
    context: AuditContext,
    stored_profile: RepositoryProfile | None,
) -> RepositoryProfile:
    """Profile at acknowledgment: merge baseline with observations through compare_end."""
    if context.baseline_profile.frozen:
        return context.baseline_profile
    fresh = build_profile(
        timeline,
        baseline_until=context.compare_end,
        compare_start=context.compare_start,
        compare_end=context.compare_end,
    )
    if stored_profile is None:
        return fresh
    merged = stored_profile.model_copy(deep=True)
    merged.privileged_mergers |= fresh.privileged_mergers
    merged.privileged_releasers |= fresh.privileged_releasers
    merged.merged_pr_authors |= fresh.merged_pr_authors
    merged.pr_merge_shas |= fresh.pr_merge_shas
    merged.release_publishers_github |= fresh.release_publishers_github
    merged.release_publishers_registry |= fresh.release_publishers_registry
    merged.dependency_edges |= fresh.dependency_edges
    merged.profile_built_until = context.compare_end
    for login, dt in fresh.first_contribution_at.items():
        prev = merged.first_contribution_at.get(login)
        if prev is None or dt < prev:
            merged.first_contribution_at[login] = dt
    for login, dt in fresh.first_privilege_at.items():
        prev = merged.first_privilege_at.get(login)
        if prev is None or dt < prev:
            merged.first_privilege_at[login] = dt
    for login, signing in fresh.signing_by_login.items():
        merged.signing_by_login[login] = signing
    merged.pr_review = fresh.pr_review
    merged.integration_mode = fresh.integration_mode
    merged.release_baseline = fresh.release_baseline
    return merged
