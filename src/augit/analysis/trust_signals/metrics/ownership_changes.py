from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class OwnershipChangesMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="ownership_changes",
        label="Ownership changes",
        category="governance",
        description="Repository URL or name change from integrity refetch.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del profile, context

        moved = [
            e for e in timeline.integrity_events if e.get("subtype") == "repo_moved"
        ]
        if not moved:
            return []

        comparisons: list[ComparisonRow] = []
        evidence: list[str] = []
        for e in moved[:3]:
            exp = e.get("expected") or {}
            obs = e.get("observed") or {}
            evidence.append(f"observed at {e.get('observed_at')}")
            comparisons.append(
                ComparisonRow(
                    subject="repository identity",
                    baseline=str(exp.get("canonical_url") or exp),
                    observed=str(obs.get("canonical_url") or obs),
                )
            )

        return [
            SignalDraft(
                title="Repository identity changed",
                summary="Integrity refetch reports a change in canonical URL or repository name.",
                evidence=evidence,
                comparisons=comparisons,
            )
        ]
