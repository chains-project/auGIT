from augit.analysis.profile import SHORT_PRIVILEGE_DAYS, AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class RoleChangesMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="role_changes",
        label="Role changes",
        category="governance",
        description="New merge or release author vs. profile; short time-to-privilege (permission API proxy).",
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

        for rel in timeline.releases:
            author = rel.get("author_login")
            dt = rel.get("published_dt")
            if not author or not dt:
                continue
            if author not in profile.privileged_releasers:
                tag = rel.get("tag_name")
                evidence.append(
                    f"{author}: published release {tag} on {format_dt(dt)} "
                    f"(new release author vs. profile)"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"{author} (release {tag})",
                        baseline=(
                            f"privileged releasers: "
                            f"{', '.join(sorted(profile.privileged_releasers)) or 'none'}"
                        ),
                        observed=f"published {tag} on {format_dt(dt)}",
                    )
                )
                first = profile.first_contribution_at.get(author)
                if first and (dt - first).days <= SHORT_PRIVILEGE_DAYS:
                    evidence.append(
                        f"{author}: {(dt - first).days} days from first contribution to release"
                    )

        for pr in timeline.merged_prs:
            author = pr.get("merged_by_login")
            dt = pr.get("merged_dt")
            if not author or not dt:
                continue
            if author not in profile.privileged_mergers:
                num = pr.get("number")
                evidence.append(
                    f"{author}: merged PR #{num} on {format_dt(dt)} "
                    f"(new merge author vs. profile)"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=f"{author} (PR #{num})",
                        baseline=(
                            f"privileged mergers: "
                            f"{', '.join(sorted(profile.privileged_mergers)) or 'none'}"
                        ),
                        observed=f"merged PR #{num} on {format_dt(dt)}",
                    )
                )
                first = profile.first_contribution_at.get(author)
                if first and (dt - first).days <= SHORT_PRIVILEGE_DAYS:
                    evidence.append(
                        f"{author}: {(dt - first).days} days from first contribution to merge"
                    )

        if not evidence:
            return []

        return [
            SignalDraft(
                title="New merge or release capability",
                summary=(
                    "Logins that publish releases or merge pull requests in the compare window "
                    "but were not privileged in the baseline profile."
                ),
                evidence=evidence[:12],
                comparisons=comparisons[:12],
            )
        ]
