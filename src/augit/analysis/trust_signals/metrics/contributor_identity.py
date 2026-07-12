from augit.analysis.profile import AuditContext, RepositoryProfile, SigningProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec
from augit.signing import normalize_signing_key_id


def _signing_profile_from_commits(
    commits: list[dict],
) -> dict[str, SigningProfile]:
    signing: dict[str, SigningProfile] = {}
    for commit in commits:
        author = commit.get("author_login")
        if not author:
            continue
        key_id = normalize_signing_key_id(commit.get("signer_key_id"))
        if not commit.get("verified") or not key_id:
            continue
        entry = signing.setdefault(author, SigningProfile())
        entry.ever_signed = True
        if key_id not in entry.key_ids:
            entry.key_ids.append(key_id)
    return signing


@register_metric
class ContributorIdentityMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="contributor_identity",
        label="Contributor identity",
        category="contributor",
        description="Signing key change or loss of signing vs. learned profile.",
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        window_signing = _signing_profile_from_commits(timeline.commits)

        evidence: list[str] = []
        comparisons: list[ComparisonRow] = []
        for author, current in window_signing.items():
            baseline = profile.signing_by_login.get(author)
            if baseline is None:
                continue
            if baseline.ever_signed and not current.ever_signed:
                evidence.append(f"{author}: stopped signing commits in compare window")
                comparisons.append(
                    ComparisonRow(
                        subject=author,
                        baseline=f"signed commits (keys: {', '.join(baseline.key_ids) or 'none'})",
                        observed="no signed commits in window",
                    )
                )
            elif not baseline.ever_signed and current.ever_signed:
                evidence.append(
                    f"{author}: started signing commits (not seen in baseline)"
                )
                comparisons.append(
                    ComparisonRow(
                        subject=author,
                        baseline="no signing in baseline",
                        observed=f"signed in window (keys: {', '.join(current.key_ids)})",
                    )
                )
            elif baseline.key_ids and current.key_ids:
                base_keys = set(baseline.key_ids)
                new_keys = set(current.key_ids) - base_keys
                if new_keys:
                    evidence.append(f"{author}: new signing key(s) {sorted(new_keys)}")
                    comparisons.append(
                        ComparisonRow(
                            subject=author,
                            baseline=f"keys: {', '.join(sorted(base_keys))}",
                            observed=f"keys: {', '.join(sorted(set(current.key_ids)))}",
                        )
                    )

        if not evidence:
            return []

        return [
            SignalDraft(
                title="Commit signing behaviour changed",
                summary="Signing key change or loss of signing vs. learned profile.",
                evidence=evidence[:10],
                comparisons=comparisons[:10],
            )
        ]
