from augit.analysis.profile import AuditContext
from augit.analysis.timeline import RepoTimeline, filter_timeline_by_window
from augit.analysis.trust_signals.finding import Finding
from augit.analysis.trust_signals.registry import in_scope_metrics, instantiate_metrics


def detect_findings(timeline: RepoTimeline, context: AuditContext) -> list[Finding]:
    window = filter_timeline_by_window(
        timeline,
        since=context.compare_start,
        until=context.compare_end,
    )
    profile = context.baseline_profile

    findings: list[Finding] = []
    for metric in instantiate_metrics():
        drafts = metric.detect(window, profile, context)
        for draft in drafts:
            findings.append(metric.to_finding(draft))

    findings.sort(key=lambda f: f.metric_label)
    return findings


def overall_status(findings: list[Finding]) -> str:
    return "findings" if findings else "ok"


IN_SCOPE_METRICS = in_scope_metrics()
