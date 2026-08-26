from datetime import datetime

from augit.analysis.profile import RepositoryProfile


def format_dt(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.astimezone().strftime("%Y-%m-%d")


def normalize_version_label(label: str) -> str:
    """Normalize a Git tag or registry version for equality checks.

    Treats optional leading ``v``/``V`` as equivalent when it prefixes a digit,
    so ``2.34.2`` matches ``v2.34.2``.
    """
    s = label.strip()
    if len(s) >= 2 and s[0] in "vV" and s[1].isdigit():
        return s[1:]
    return s


def version_labels_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return normalize_version_label(a) == normalize_version_label(b)


def has_matching_version_label(needle: str | None, haystack: list[str] | set[str]) -> bool:
    if not needle:
        return False
    target = normalize_version_label(needle)
    return any(normalize_version_label(item) == target for item in haystack if item)


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
            (
                f"Known direct-push authors: {len(profile.direct_push_authors)}"
                + (
                    f" ({', '.join(sorted(profile.direct_push_authors)[:8])}"
                    + (
                        f", …"
                        if len(profile.direct_push_authors) > 8
                        else ""
                    )
                    + ")"
                    if profile.direct_push_authors
                    else ""
                )
            ),
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
