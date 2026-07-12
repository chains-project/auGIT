from typing import Any

from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import (
    branch_label,
    is_default_branch,
)
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec

_INTEGRITY_NOISE_SUBTYPES = frozenset({"tag_added", "commit_added"})
_INTEGRITY_ACTION_SUBTYPES = frozenset(
    {"commit_missing", "tag_retargeted", "repo_moved", "pr_missing"}
)


@register_metric
class HistoryIntegrityMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="history_integrity",
        label="History integrity",
        category="integrity",
        description="History drift events from integrity refetch vs. stored log.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        actionable: list[dict[str, Any]] = []
        for ev in timeline.integrity_events:
            subtype = ev.get("subtype") or ""
            severity = ev.get("severity") or "low"
            branch = branch_label(ev.get("expected"))
            if subtype in _INTEGRITY_NOISE_SUBTYPES:
                if (
                    subtype == "tag_added"
                    and not profile.release_baseline.tag_aligned_releases
                ):
                    pass
                else:
                    continue
            if subtype in _INTEGRITY_ACTION_SUBTYPES:
                if (
                    severity == "high"
                    or is_default_branch(branch)
                    or subtype == "repo_moved"
                ):
                    actionable.append(ev)
                continue
            if severity == "high":
                actionable.append(ev)

        if not actionable:
            return []

        lines: list[str] = []
        comparisons: list[ComparisonRow] = []
        for ev in actionable[:8]:
            exp = ev.get("expected") or {}
            obs = ev.get("observed") or {}
            subtype = ev.get("subtype")
            if subtype == "commit_missing":
                lines.append(
                    f"{subtype}: {exp.get('sha', '?')[:8]} missing on {exp.get('branch', '?')}"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"commit {exp.get('sha', '?')[:8]}",
                        baseline=f"present on branch {exp.get('branch', '?')}",
                        observed="missing on refetch",
                    )
                )
            elif subtype == "tag_retargeted":
                lines.append(
                    f"{subtype}: tag {exp.get('tag')} moved "
                    f"({exp.get('sha', '?')[:8]} → {obs.get('sha', '?')[:8]})"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"tag {exp.get('tag')}",
                        baseline=f"points to {exp.get('sha', '?')[:8]}",
                        observed=f"now points to {obs.get('sha', '?')[:8]}",
                    )
                )
            elif subtype == "repo_moved":
                lines.append(f"{subtype}: repository identity changed")
                comparisons.append(
                    ComparisonRow(
                        subject="repository identity",
                        baseline=str(exp.get("canonical_url") or exp),
                        observed=str(obs.get("canonical_url") or obs),
                    )
                )
            else:
                lines.append(f"{subtype} ({ev.get('severity')})")
                comparisons.append(
                    ComparisonRow(
                        subject=str(subtype),
                        baseline=str(exp) if exp else "recorded in audit log",
                        observed=str(obs) if obs else "live refetch",
                    )
                )

        return [
            SignalDraft(
                title="History drift detected",
                summary=f"{len(actionable)} actionable integrity signal(s) from check runs.",
                evidence=lines,
                comparisons=comparisons,
            )
        ]
