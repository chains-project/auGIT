from datetime import timedelta

from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec

RELEASE_BURST_DAYS = 7


def _release_burst_clusters(dates: list) -> list[list]:
    if not dates:
        return []
    sorted_dates = sorted(dates)
    clusters: list[list] = [[sorted_dates[0]]]
    for dt in sorted_dates[1:]:
        if dt - clusters[-1][-1] <= timedelta(days=RELEASE_BURST_DAYS):
            clusters[-1].append(dt)
        else:
            clusters.append([dt])
    return [cluster for cluster in clusters if len(cluster) >= 2]


@register_metric
class UnusualReleasePatternMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="unusual_release_pattern",
        label="Unusual release pattern",
        category="release",
        description="Tag/registry coupling anomalies, version gaps, and release bursts vs. profile.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        findings: list[SignalDraft] = []

        window_tags = {
            t.get("tag_name"): t.get("sha") for t in timeline.tags if t.get("tag_name")
        }

        for rel in timeline.releases:
            tag = rel.get("tag_name")
            dt = rel.get("published_dt")
            author = rel.get("author_login") or "unknown"
            if not dt:
                continue

            if (
                profile.release_baseline.tag_aligned_releases
                and tag
                and tag not in window_tags
            ):
                findings.append(
                    SignalDraft(
                        title="Release without matching tag in window",
                        summary=(
                            f"Release {tag} by {author} has no corresponding tag event in the compare window."
                        ),
                        evidence=[f"published {format_dt(dt)}"],
                        comparisons=[
                            ComparisonRow(
                                subject=f"release {tag}",
                                baseline="releases typically have matching tag events",
                                observed=f"release by {author} on {format_dt(dt)}; no tag in window",
                            )
                        ],
                    )
                )

        by_author: dict[str, list] = {}
        all_dates = []
        for rel in timeline.releases:
            dt = rel.get("published_dt")
            author = rel.get("author_login") or "unknown"
            if not dt:
                continue
            by_author.setdefault(author, []).append(dt)
            all_dates.append(dt)

        for author, dates in by_author.items():
            clusters = _release_burst_clusters(dates)
            if not clusters:
                continue
            evidence = [
                f"{format_dt(cluster[0])} → {format_dt(cluster[-1])} ({len(cluster)} releases)"
                for cluster in clusters
            ]
            release_count = sum(len(cluster) for cluster in clusters)
            burst_count = len(clusters)
            findings.append(
                SignalDraft(
                    title="Release burst",
                    summary=(
                        f"{author} published {release_count} releases across "
                        f"{burst_count} burst{'s' if burst_count != 1 else ''} within "
                        f"{RELEASE_BURST_DAYS} days."
                    ),
                    evidence=evidence,
                    comparisons=[
                        ComparisonRow(
                            subject=author,
                            baseline=(
                                f"typical inter-release gap: "
                                f"{profile.release_baseline.median_inter_release_days or 'unknown'} days"
                            ),
                            observed=(
                                f"{release_count} releases in {burst_count} burst(s) "
                                f"within {RELEASE_BURST_DAYS} days"
                            ),
                        )
                    ],
                )
            )

        if len(all_dates) >= 1 and profile.release_baseline.median_inter_release_days:
            all_dates.sort()
            if len(all_dates) >= 2:
                gap = (all_dates[-1] - all_dates[-2]).days
                baseline = profile.release_baseline.median_inter_release_days
                if gap > baseline * 3 and gap >= 180:
                    findings.append(
                        SignalDraft(
                            title="Release after long gap",
                            summary=f"Gap of {gap} days since prior release exceeds project baseline.",
                            evidence=[
                                f"between {format_dt(all_dates[-2])} and {format_dt(all_dates[-1])}"
                            ],
                            comparisons=[
                                ComparisonRow(
                                    subject="release cadence",
                                    baseline=f"median inter-release gap: {baseline:.0f} days",
                                    observed=f"gap of {gap} days before latest release",
                                )
                            ],
                        )
                    )

        for reg in timeline.registry_versions:
            version = reg.get("version")
            if version and profile.release_baseline.tag_aligned_releases:
                matching_tag = version in window_tags or any(
                    r.get("tag_name") == version for r in timeline.releases
                )
                if not matching_tag:
                    findings.append(
                        SignalDraft(
                            title="Registry version without matching tag",
                            summary=(
                                f"Registry version {version} has no matching Git tag in the compare window."
                            ),
                            evidence=[f"registry={reg.get('registry')}"],
                            comparisons=[
                                ComparisonRow(
                                    subject=f"version {version}",
                                    baseline="registry versions typically have matching tags",
                                    observed=f"{reg.get('registry')} version {version} without tag",
                                )
                            ],
                        )
                    )

        return findings
