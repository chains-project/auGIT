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
        description=(
            "New exercised write privilege vs. profile: first merge or first "
            "direct push by a login (once per login in the window)."
        ),
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
        reported_logins: set[str] = set()

        for pr in timeline.merged_prs:
            author = (pr.get("merged_by_login") or "").strip()
            dt = pr.get("merged_dt")
            if not author or not dt:
                continue
            if author in profile.privileged_mergers:
                continue
            if author in reported_logins:
                continue
            reported_logins.add(author)
            num = pr.get("number")
            evidence.append(
                f"{author}: merged PR #{num} on {format_dt(dt)} (new merge author vs. profile)"
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

        known_merge_shas = set(profile.pr_merge_shas)
        for pr in timeline.merged_prs:
            for key in ("merge_commit_sha", "head_sha"):
                sha = pr.get(key)
                if sha:
                    known_merge_shas.add(sha)

        for commit in timeline.commits:
            sha = commit.get("sha")
            author = (commit.get("author_login") or "").strip()
            dt = commit.get("committed_dt")
            if not sha or not author or not dt:
                continue
            if sha in known_merge_shas:
                continue
            if author in profile.direct_push_authors:
                continue
            if author in reported_logins:
                continue
            reported_logins.add(author)
            evidence.append(
                f"{author}: first direct push on {format_dt(dt)} "
                f"(commit {sha[:8]}; new write privilege vs. profile)"
            )
            comparisons.append(
                ComparisonRow(
                    subject=f"{author} (direct push {sha[:8]})",
                    baseline=(
                        "known direct pushers: "
                        f"{', '.join(sorted(profile.direct_push_authors)[:8]) or 'none'}; "
                        "privileged mergers: "
                        f"{', '.join(sorted(profile.privileged_mergers)[:8]) or 'none'}"
                    ),
                    observed=f"direct commit on {format_dt(dt)}",
                )
            )
            first = profile.first_contribution_at.get(author)
            if first and (dt - first).days <= SHORT_PRIVILEGE_DAYS:
                evidence.append(
                    f"{author}: {(dt - first).days} days from first contribution "
                    f"to first direct push"
                )

        if not evidence:
            return []

        return [
            SignalDraft(
                title="New write privilege",
                summary=(
                    "Logins that newly exercise repository write privilege in the "
                    "compare window via a first pull-request merge or a first direct "
                    "push, relative to the baseline profile."
                ),
                evidence=evidence[:12],
                comparisons=comparisons[:12],
            )
        ]
