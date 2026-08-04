from augit.analysis.profile import AuditContext, IntegrationMode, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class IrregularCommitsMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="irregular_commits",
        label="Irregular commits",
        category="contributor",
        description="Commits on the default branch without the project's usual integration path.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        self_merge_evidence: list[str] = []
        self_merge_comparisons: list[ComparisonRow] = []
        for pr in timeline.merged_prs:
            author = (pr.get("author_login") or "").strip()
            merged_by = (pr.get("merged_by_login") or "").strip()
            if not author or not merged_by:
                continue
            if author != merged_by:
                continue

            # Flag only when it appears to be self-merged without additional reviewers.
            # We don't currently persist reviewer identities, so approximate by presence of review signals.
            review_count = pr.get("review_count") or 0
            review_comment_count = pr.get("review_comment_count") or 0
            review_states = pr.get("review_states") or []
            if review_count > 0 or review_comment_count > 0 or review_states:
                continue

            num = pr.get("number") or "?"
            base = pr.get("base_branch") or "?"
            merged_at = pr.get("merged_at") or "?"
            self_merge_evidence.append(
                f"{author}: self-merged PR #{num} into {base} at {merged_at} (no reviews)"
            )
            self_merge_comparisons.append(
                ComparisonRow(
                    subject=f"PR #{num} ({author})",
                    baseline="merged by someone other than author, or with review signals",
                    observed=f"self-merged into {base} at {merged_at} with no reviews",
                )
            )

        known_merge_shas = set(profile.pr_merge_shas)
        for pr in timeline.merged_prs:
            for key in ("merge_commit_sha", "head_sha"):
                sha = pr.get(key)
                if sha:
                    known_merge_shas.add(sha)

        commit_evidence: list[str] = []
        commit_comparisons: list[ComparisonRow] = []
        for commit in timeline.commits:
            sha = commit.get("sha")
            author = (commit.get("author_login") or "").strip() or None
            dt = commit.get("committed_dt")
            if not sha or not dt:
                continue
            if sha in known_merge_shas:
                continue

            if author is None:
                commit_evidence.append(
                    f"unlinked author: commit {sha[:8]} on {format_dt(dt)} "
                    f"(no GitHub user)"
                )
                commit_comparisons.append(
                    ComparisonRow(
                        subject=f"commit {sha[:8]} (unlinked author)",
                        baseline=(
                            "commits expected to have a linked GitHub identity; "
                            f"known direct pushers: "
                            f"{', '.join(sorted(profile.direct_push_authors)[:8]) or 'none'}"
                        ),
                        observed=f"direct commit on {format_dt(dt)} with null author_login",
                    )
                )
                continue

            if profile.integration_mode == IntegrationMode.PR_REVIEWED:
                commit_evidence.append(
                    f"{author}: commit {sha[:8]} on {format_dt(dt)} not linked to a merged PR"
                )
                commit_comparisons.append(
                    ComparisonRow(
                        subject=f"commit {sha[:8]} ({author})",
                        baseline=(
                            f"integration mode={profile.integration_mode.value}; "
                            f"commits expected via merged PR"
                        ),
                        observed=f"direct commit on {format_dt(dt)} (not in PR merge SHAs)",
                    )
                )
                continue

            # DIRECT_PUSH_OK or MIXED: allow known baseline direct pushers.
            if author in profile.direct_push_authors:
                continue
            commit_evidence.append(
                f"{author}: commit {sha[:8]} on {format_dt(dt)} "
                f"(new direct pusher; not seen in baseline)"
            )
            commit_comparisons.append(
                ComparisonRow(
                    subject=f"commit {sha[:8]} ({author})",
                    baseline=(
                        f"integration mode={profile.integration_mode.value}; "
                        f"known direct pushers: "
                        f"{', '.join(sorted(profile.direct_push_authors)[:8]) or 'none'}"
                    ),
                    observed=f"direct commit on {format_dt(dt)} by login not in baseline",
                )
            )

        drafts: list[SignalDraft] = []
        if self_merge_evidence:
            drafts.append(
                SignalDraft(
                    title="Self-merged pull request without review",
                    summary=f"{len(self_merge_evidence)} PR(s) were merged by their author with no review signal.",
                    evidence=self_merge_evidence[:10],
                    comparisons=self_merge_comparisons[:10],
                )
            )
        if commit_evidence:
            drafts.append(
                SignalDraft(
                    title="Commit without usual integration path",
                    summary=(
                        "Commits in the compare window that are not linked to a merged pull request "
                        "and deviate from the project's usual integration path or known direct pushers."
                    ),
                    evidence=commit_evidence[:10],
                    comparisons=commit_comparisons[:10],
                )
            )
        return drafts
