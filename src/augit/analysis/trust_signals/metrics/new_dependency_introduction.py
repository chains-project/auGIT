from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class NewDependencyIntroductionMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="new_dependency_introduction",
        label="New dependency introduction",
        category="dependency",
        description="New direct dependency edges in compare window with commit/PR attribution.",
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
        new_edges: set[str] = set()

        baseline_edges = ", ".join(sorted(profile.dependency_edges)[:20])
        if len(profile.dependency_edges) > 20:
            baseline_edges += f", … ({len(profile.dependency_edges)} total)"

        for change in timeline.dependency_changes:
            added = change.get("added") or []
            author = change.get("author_login") or "unknown"
            dt = change.get("event_ts")
            for dep in added:
                dep_str = str(dep)
                if dep_str not in profile.dependency_edges:
                    new_edges.add(dep_str)
                    pr_num = change.get("pr_number")
                    evidence.append(
                        f"{author}: added {dep_str} "
                        f"(commit {str(change.get('commit_sha', ''))[:8]}, "
                        f"PR #{pr_num}) on {format_dt(dt)}"
                    )
                    comparisons.append(
                        ComparisonRow(
                            subject=dep_str,
                            baseline=baseline_edges or "no known direct dependencies",
                            observed=(
                                f"added by {author} in PR #{pr_num} on {format_dt(dt)}"
                            ),
                        )
                    )

        if (
            not evidence
            and timeline.registry_versions
            and not timeline.dependency_changes
        ):
            versions = timeline.registry_versions[-3:]
            lines = [f"{v.get('version')} at {v.get('published_at')}" for v in versions]
            version_comparisons = [
                ComparisonRow(
                    subject=str(v.get("version")),
                    baseline="no manifest diff events collected",
                    observed=f"registry version at {v.get('published_at')}",
                )
                for v in versions
            ]
            return [
                SignalDraft(
                    title="Registry versions observed (no manifest diff events)",
                    summary=(
                        "Registry versions are present but no dependency_manifest_change "
                        "events were collected for this repository."
                    ),
                    evidence=lines,
                    comparisons=version_comparisons,
                )
            ]

        if not evidence:
            return []

        footprint_growth = len(profile.dependency_edges | new_edges) - len(
            profile.dependency_edges
        )
        summary = (
            f"{len(new_edges)} new direct dependency edge(s) in the compare window."
        )
        if footprint_growth > 5:
            summary += f" Footprint grew by {footprint_growth} edges vs. baseline."

        return [
            SignalDraft(
                title="New dependencies introduced",
                summary=summary,
                evidence=evidence[:10],
                comparisons=comparisons[:10],
            )
        ]
