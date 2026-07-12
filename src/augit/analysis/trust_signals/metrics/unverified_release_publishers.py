from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class UnverifiedReleasePublishersMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="unverified_release_publishers",
        label="Unverified release publishers",
        category="release",
        description="New GitHub or registry release publisher vs. profile (signature metadata when available).",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        evidence: list[str] = []
        comparisons: list[ComparisonRow] = []
        github_baseline = (
            ", ".join(sorted(profile.release_publishers_github)) or "none"
        )
        registry_baseline = (
            ", ".join(sorted(profile.release_publishers_registry)) or "none"
        )

        for rel in timeline.releases:
            author = rel.get("author_login")
            dt = rel.get("published_dt")
            if not author or not dt:
                continue
            if author not in profile.release_publishers_github:
                tag = rel.get("tag_name")
                evidence.append(
                    f"GitHub: {author} published {tag} on {format_dt(dt)}"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"GitHub {author} ({tag})",
                        baseline=f"known publishers: {github_baseline}",
                        observed=f"published {tag} on {format_dt(dt)}",
                    )
                )

        for reg in timeline.registry_versions:
            uploaders = reg.get("uploaders") or []
            version = reg.get("version")
            for uploader in uploaders:
                u = str(uploader)
                if u not in profile.release_publishers_registry:
                    evidence.append(
                        f"{reg.get('registry')}: new uploader {u} for version {version}"
                    )
                    comparisons.append(
                        ComparisonRow(
                            subject=f"{reg.get('registry')} {u}",
                            baseline=f"known uploaders: {registry_baseline}",
                            observed=f"uploaded version {version}",
                        )
                    )
            author = reg.get("author_login")
            if author and author not in profile.release_publishers_registry:
                evidence.append(
                    f"{reg.get('registry')}: new publisher {author} for {version}"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"{reg.get('registry')} {author}",
                        baseline=f"known publishers: {registry_baseline}",
                        observed=f"published version {version}",
                    )
                )

        if not evidence:
            return []

        return [
            SignalDraft(
                title="New release publisher",
                summary="Release author or registry uploader not seen in the baseline profile.",
                evidence=evidence[:10],
                comparisons=comparisons[:10],
            )
        ]
