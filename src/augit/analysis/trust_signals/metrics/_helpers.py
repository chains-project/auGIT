from datetime import datetime

from augit.analysis.profile import RepositoryProfile


def format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.astimezone().strftime("%Y-%m-%d")


def branch_label(expected: object) -> str:
    if isinstance(expected, dict):
        return str(expected.get("branch", ""))
    return ""


def is_default_branch(branch: str) -> bool:
    return branch in ("main", "master", "_from_audit_log")


def summarize_baseline_by_category(profile: RepositoryProfile) -> dict[str, list[str]]:
    """Baseline profile facts grouped by trust-signal category."""
    pr = profile.pr_review
    rel = profile.release_baseline
    signing_authors = ", ".join(sorted(profile.signing_by_login)) or "none"
    return {
        "contributor": [
            f"Integration mode: {profile.integration_mode.value}",
            (
                f"PR review baseline: median {pr.median_review_comments:.0f} comments, "
                f"{pr.median_reviews:.0f} reviews ({pr.merged_pr_count} merged PRs in profile)"
            ),
            f"Merged PR authors in profile: {len(profile.merged_pr_authors)}",
            f"Authors with signing history: {signing_authors}",
        ],
        "governance": [
            (
                f"Privileged mergers: "
                f"{', '.join(sorted(profile.privileged_mergers)) or 'none'}"
            ),
            (
                f"Privileged releasers: "
                f"{', '.join(sorted(profile.privileged_releasers)) or 'none'}"
            ),
        ],
        "release": [
            (
                f"GitHub release publishers: "
                f"{', '.join(sorted(profile.release_publishers_github)) or 'none'}"
            ),
            (
                f"Registry release publishers: "
                f"{', '.join(sorted(profile.release_publishers_registry)) or 'none'}"
            ),
            *(
                [f"Typical inter-release gap: {rel.median_inter_release_days:.0f} days"]
                if rel.median_inter_release_days is not None
                else []
            ),
            (
                f"Tag-aligned releases in baseline: "
                f"{'yes' if rel.tag_aligned_releases else 'no'}"
            ),
        ],
        "dependency": [
            f"Known direct dependency edges: {len(profile.dependency_edges)}",
            *(
                [
                    "Sample edges: "
                    + ", ".join(sorted(profile.dependency_edges)[:12])
                    + (
                        f" … ({len(profile.dependency_edges)} total)"
                        if len(profile.dependency_edges) > 12
                        else ""
                    )
                ]
                if profile.dependency_edges
                else ["No dependency edges recorded in baseline profile"]
            ),
        ],
        "integrity": [
            (
                f"Tag-aligned releases in baseline: "
                f"{'yes' if rel.tag_aligned_releases else 'no'}"
            ),
            "Integrity signals require a prior augit check run",
        ],
    }
