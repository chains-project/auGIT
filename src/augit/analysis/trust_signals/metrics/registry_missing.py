from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class RegistryMissingMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="registry_missing",
        label="Registry deletion / missing package",
        category="release",
        description=(
            "Registry returned a missing/not found response for the package "
            "(global signal, not limited to the compare window)."
        ),
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del profile
        del context

        missing = [m for m in timeline.registry_missing if m.get("registry") == "pypi"]
        if not missing:
            return []

        lines: list[str] = []
        for m in missing[:5]:
            name = m.get("name") or "unknown"
            status = m.get("http_status") or "unknown"
            url = m.get("url") or ""
            lines.append(f"PyPI returned {status} for {name} ({url})")

        return [
            SignalDraft(
                title="Package missing from registry",
                summary=(
                    "The registry returned 'not found' for this package. "
                    "This can indicate administrative takedown / deletion (common for malicious packages)."
                ),
                evidence=lines,
            )
        ]

