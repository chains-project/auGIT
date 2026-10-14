from datetime import timedelta

from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric
from augit.analysis.trust_signals.metrics._helpers import (
    format_dt,
    has_matching_version_label,
    version_labels_match,
)
from augit.analysis.trust_signals.registry import register_metric
from augit.analysis.trust_signals.spec import MetricSpec
from augit.analysis.version_labels import normalize_version_label, parse_version_tuple

RELEASE_BURST_DAYS = 7
SHORT_TAG_REGISTRY_FRACTION = 0.25
MIN_BASELINE_TAG_REGISTRY_MEDIAN_DAYS = 1.0
VERSION_MAJOR_JUMP = 1


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


def _release_time_by_version(timeline: RepoTimeline) -> dict[str, object]:
    """Map normalized version label -> earliest release/tag timestamp."""
    times: dict[str, object] = {}
    for rel in timeline.releases:
        tag = rel.get("tag_name")
        dt = rel.get("published_dt")
        if not tag or not dt:
            continue
        key = normalize_version_label(tag)
        prev = times.get(key)
        if prev is None or dt < prev:
            times[key] = dt
    for tag in timeline.tags:
        name = tag.get("tag_name")
        dt = tag.get("event_ts")
        if not name or not dt:
            continue
        key = normalize_version_label(name)
        if key in times:
            continue
        times[key] = dt
    return times


@register_metric
class UnusualReleasePatternMetric(TrustMetric):
    spec = MetricSpec(
        metric_id="unusual_release_pattern",
        label="Unusual release pattern",
        category="release",
        description=(
            "Tag/registry coupling, short tag-to-registry delay, version jumps, "
            "and release bursts vs. profile."
        ),
    )

    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        del context

        findings: list[SignalDraft] = []

        window_tag_names = [
            t.get("tag_name") for t in timeline.tags if t.get("tag_name")
        ]

        for rel in timeline.releases:
            tag = rel.get("tag_name")
            dt = rel.get("published_dt")
            author = rel.get("author_login") or "unknown"
            if not dt:
                continue

            if (
                profile.release_baseline.tag_aligned_releases
                and tag
                and not has_matching_version_label(tag, window_tag_names)
            ):
                findings.append(
                    SignalDraft(
                        title="Release without matching tag in window",
                        summary=(
                            f"Release {tag} by {author} has no corresponding Git tag."
                        ),
                        evidence=[f"published {format_dt(dt)}"],
                        comparisons=[
                            ComparisonRow(
                                subject=f"release {tag}",
                                baseline="releases typically have matching tag events",
                                observed=(
                                    f"release by {author} on {format_dt(dt)}. "
                                    "no matching tag"
                                ),
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
                            summary=(
                                f"Gap of {gap} days since prior release exceeds "
                                "project baseline."
                            ),
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
                matching_tag = has_matching_version_label(
                    version, window_tag_names
                ) or any(
                    version_labels_match(version, r.get("tag_name"))
                    for r in timeline.releases
                )
                if not matching_tag:
                    findings.append(
                        SignalDraft(
                            title="Registry version without matching tag",
                            summary=(
                                f"Registry version {version} has no matching Git tag."
                            ),
                            evidence=[f"registry={reg.get('registry')}"],
                            comparisons=[
                                ComparisonRow(
                                    subject=f"version {version}",
                                    baseline="registry versions typically have matching tags",
                                    observed=(
                                        f"{reg.get('registry')} version {version} "
                                        "without tag"
                                    ),
                                )
                            ],
                        )
                    )

        release_times = _release_time_by_version(timeline)
        median_delay = profile.release_baseline.median_tag_registry_delay_days
        if (
            median_delay is not None
            and median_delay >= MIN_BASELINE_TAG_REGISTRY_MEDIAN_DAYS
        ):
            short_limit = median_delay * SHORT_TAG_REGISTRY_FRACTION
            for reg in timeline.registry_versions:
                version = reg.get("version")
                pub = reg.get("published_dt")
                if not version or not pub:
                    continue
                release_dt = release_times.get(normalize_version_label(version))
                if release_dt is None:
                    continue
                delay_days = (pub - release_dt).total_seconds() / 86400.0
                if delay_days < 0:
                    delay_days = 0.0
                if delay_days >= short_limit:
                    continue
                findings.append(
                    SignalDraft(
                        title="Short tag-to-registry delay",
                        summary=(
                            f"Registry version {version} appeared "
                            f"{delay_days:.1f} days after the matching release/tag, "
                            f"below the project baseline median of {median_delay:.1f} days."
                        ),
                        evidence=[
                            f"registry={reg.get('registry')}",
                            f"release/tag at {format_dt(release_dt)}",
                            f"registry at {format_dt(pub)}",
                        ],
                        comparisons=[
                            ComparisonRow(
                                subject=f"version {version}",
                                baseline=(
                                    f"median tag-to-registry delay: "
                                    f"{median_delay:.1f} days"
                                ),
                                observed=f"delay of {delay_days:.1f} days",
                            )
                        ],
                    )
                )

        version_events: list[tuple[object, str, str]] = []
        for rel in timeline.releases:
            label = rel.get("tag_name")
            dt = rel.get("published_dt")
            parsed = parse_version_tuple(label)
            if label and dt and parsed is not None:
                version_events.append((dt, label, "GitHub release"))
        for reg in timeline.registry_versions:
            label = reg.get("version")
            dt = reg.get("published_dt")
            parsed = parse_version_tuple(label)
            if label and dt and parsed is not None:
                version_events.append(
                    (dt, label, f"{reg.get('registry') or 'registry'} version")
                )
        version_events.sort(key=lambda item: item[0])

        prev_label = profile.release_baseline.latest_version_label
        prev_tuple = profile.release_baseline.latest_version_tuple
        for dt, label, source in version_events:
            current = parse_version_tuple(label)
            if current is None:
                continue
            if prev_tuple is not None and prev_label is not None:
                if current < prev_tuple:
                    findings.append(
                        SignalDraft(
                            title="Out-of-order version",
                            summary=(
                                f"{source} {label} sorts below prior version "
                                f"{prev_label}."
                            ),
                            evidence=[f"published {format_dt(dt)}"],
                            comparisons=[
                                ComparisonRow(
                                    subject=label,
                                    baseline=f"prior published version: {prev_label}",
                                    observed=f"{source} on {format_dt(dt)}",
                                )
                            ],
                        )
                    )
                elif current[0] - prev_tuple[0] > VERSION_MAJOR_JUMP:
                    findings.append(
                        SignalDraft(
                            title="Unusual version jump",
                            summary=(
                                f"{source} {label} jumps major version from "
                                f"{prev_label}."
                            ),
                            evidence=[f"published {format_dt(dt)}"],
                            comparisons=[
                                ComparisonRow(
                                    subject=label,
                                    baseline=f"prior published version: {prev_label}",
                                    observed=(
                                        f"major jump to {label} on {format_dt(dt)}"
                                    ),
                                )
                            ],
                        )
                    )
            prev_label = label
            prev_tuple = current

        return findings
