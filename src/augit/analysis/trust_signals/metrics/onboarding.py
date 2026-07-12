from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import format_dt
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec


@register_metric
class OnboardingMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="onboarding",
        label="Onboarding of new contributors",
        category="contributor",
        description="PR review depth deviation for new merge authors vs. project baseline.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        median_comments = profile.pr_review.median_review_comments
        median_reviews = profile.pr_review.median_reviews

        first_merge_by_author: dict[str, object] = {}
        for pr in timeline.merged_prs:
            author = pr.get("author_login")
            dt = pr.get("merged_dt")
            if not author or not dt:
                continue
            if author in profile.merged_pr_authors:
                continue
            if author not in first_merge_by_author:
                first_merge_by_author[author] = pr

        evidence: list[str] = []
        comparisons: list[ComparisonRow] = []
        for author, pr_obj in first_merge_by_author.items():
            pr = pr_obj  # type: ignore[assignment]
            comments = pr.get("review_comment_count")
            reviews = pr.get("review_count")

            thin_review = False
            if (
                median_comments > 0
                and comments is not None
                and comments < median_comments * 0.5
            ):
                thin_review = True
            if (
                median_reviews > 0
                and reviews is not None
                and reviews < max(1, median_reviews * 0.5)
            ):
                thin_review = True
            if not thin_review:
                continue

            pr_num = pr.get("number")
            evidence.append(
                f"{author}: first merged PR #{pr_num} on "
                f"{format_dt(pr.get('merged_dt'))} with thinner review than baseline "
                f"(comments={comments}, reviews={reviews})"
            )
            comparisons.append(
                ComparisonRow(
                    subject=f"{author} (PR #{pr_num})",
                    baseline=(
                        f"median review comments={median_comments:.0f}, "
                        f"reviews={median_reviews:.0f}; "
                        f"author not in baseline merged authors"
                    ),
                    observed=(
                        f"first merge on {format_dt(pr.get('merged_dt'))}: "
                        f"comments={comments}, reviews={reviews}"
                    ),
                )
            )

        if not evidence:
            return []

        return [
            SignalDraft(
                title="Unusual review pattern for new merge author",
                summary=(
                    "New merge authors whose first merged work shows unusually low review "
                    "depth compared to the project baseline."
                ),
                evidence=evidence[:10],
                comparisons=comparisons[:10],
            )
        ]
