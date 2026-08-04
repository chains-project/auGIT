from datetime import UTC, datetime, timedelta

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.timeline import load_timeline
from augit.analysis.trust_signals import detect_findings, overall_status
from augit.analysis.trust_signals.finding import Finding


def _row(
    event_type: str,
    payload: dict,
    observed_at: datetime | None = None,
) -> dict:
    return {
        "event_type": event_type,
        "category": "contributor",
        "payload": payload,
        "observed_at": observed_at or datetime.now(UTC),
    }


def test_load_timeline_sorts_closed_prs_by_merge_or_event_time():
    early = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 15, tzinfo=UTC)
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {"number": 2, "state": "closed", "merged_at": "2026-01-15T00:00:00Z"},
                observed_at=later,
            ),
            _row(
                "github_pull_request",
                {"number": 1, "state": "closed", "author_login": "a"},
                observed_at=early,
            ),
        ]
    )
    assert [pr["number"] for pr in timeline.closed_prs] == [1, 2]


def test_integrity_filters_tag_added_noise():
    timeline = load_timeline(
        [
            _row(
                "integrity_drift",
                {"subtype": "tag_added", "severity": "low"},
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=datetime.now(UTC),
    )
    assert detect_findings(timeline, context) == []


def test_integrity_surfaces_tag_retargeted():
    timeline = load_timeline(
        [
            _row(
                "integrity_drift",
                {
                    "subtype": "tag_retargeted",
                    "severity": "high",
                    "expected": {"tag": "v1", "sha": "aaa"},
                    "observed": {"tag": "v1", "sha": "bbb"},
                },
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=datetime.now(UTC),
    )
    findings = detect_findings(timeline, context)
    assert len(findings) == 1
    assert findings[0].metric_id == "history_integrity"


def test_self_merged_prs_flagged():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    recent = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "number": 12,
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "review_count": 0,
                    "review_states": [],
                    "review_comment_count": 0,
                    "merged_at": recent,
                    "state": "closed",
                    "base_branch": "main",
                },
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    matches = [f for f in findings if f.metric_id == "irregular_commits"]
    assert len(matches) == 1
    assert "alice" in "\n".join(matches[0].evidence)


def test_onboarding_skips_established_mergers():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    baseline = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {"author_login": "alice", "merged_at": baseline, "number": 1},
                baseline,
            ),
            *[
                _row(
                    "github_pull_request",
                    {"author_login": "alice", "merged_at": recent, "number": i},
                    recent,
                )
                for i in range(2, 4)
            ],
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    assert not any(
        f.metric_id == "onboarding" for f in detect_findings(timeline, context)
    )


def test_onboarding_flags_thin_review_for_new_merge_author():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": old,
                    "number": 1,
                    "state": "closed",
                    "review_comment_count": 10,
                    "review_count": 3,
                },
                old,
            ),
            _row(
                "github_pull_request",
                {
                    "author_login": "newbie",
                    "merged_by_login": "newbie",
                    "merged_at": recent,
                    "number": 2,
                    "state": "closed",
                    "review_comment_count": 0,
                    "review_count": 0,
                },
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    onboarding = [f for f in findings if f.metric_id == "onboarding"]
    assert len(onboarding) == 1
    assert "newbie" in onboarding[0].evidence[0]


def test_onboarding_does_not_flag_if_not_thin_review():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    baseline = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": baseline,
                    "number": 1,
                    "state": "closed",
                    "review_comment_count": 10,
                    "review_count": 3,
                },
                baseline,
            ),
            _row(
                "github_pull_request",
                {
                    "author_login": "newbie",
                    "merged_by_login": "newbie",
                    "merged_at": recent,
                    "number": 2,
                    "state": "closed",
                    "review_comment_count": 33,
                    "review_count": 30,
                },
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    assert not any(f.metric_id == "onboarding" for f in findings)


def test_onboarding_includes_pr_merged_in_window_even_if_created_earlier():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    created = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    merged = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": created,
                    "number": 1,
                    "state": "closed",
                    "review_comment_count": 10,
                    "review_count": 3,
                },
                created,
            ),
            _row(
                "github_pull_request",
                {
                    "author_login": "newbie",
                    "merged_by_login": "reviewer",
                    "merged_at": merged,
                    "number": 1540,
                    "state": "closed",
                    "review_comment_count": 0,
                    "review_count": 0,
                },
                created,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    onboarding = [f for f in findings if f.metric_id == "onboarding"]
    assert len(onboarding) == 1
    assert "newbie" in onboarding[0].evidence[0]
    assert "#1540" in onboarding[0].evidence[0]


def test_irregular_commits_skips_merge_commit_from_recent_pr():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    created = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    merged = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    merge_sha = "5ef77f3778f4d6bcc6d287bc6e9bfb4540223cda"
    baseline_merge_sha = "aaa1111111111111111111111111111111111111111"
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": created,
                    "number": 1,
                    "state": "closed",
                    "merge_commit_sha": baseline_merge_sha,
                    "review_comment_count": 5,
                    "review_count": 2,
                },
                created,
            ),
            _row(
                "github_commit",
                {
                    "sha": baseline_merge_sha,
                    "author_login": "alice",
                },
                created,
            ),
            _row(
                "github_pull_request",
                {
                    "author_login": "fz-rh",
                    "merged_by_login": "reviewer",
                    "merged_at": merged,
                    "number": 1540,
                    "state": "closed",
                    "merge_commit_sha": merge_sha,
                    "review_comment_count": 33,
                    "review_count": 30,
                },
                created,
            ),
            _row(
                "github_commit",
                {
                    "sha": merge_sha,
                    "author_login": "fz-rh",
                },
                merged,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    irregular = [f for f in findings if f.metric_id == "irregular_commits"]
    commit_findings = [
        f for f in irregular if f.title == "Commit without usual integration path"
    ]
    assert commit_findings == []


def test_irregular_commits_direct_push_allows_known_author():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    baseline = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_commit",
                {"sha": "aaa111111111111111111111111111111111111111", "author_login": "alice"},
                baseline,
            ),
            _row(
                "github_commit",
                {"sha": "bbb222222222222222222222222222222222222222", "author_login": "alice"},
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    assert context.baseline_profile.integration_mode.value == "direct_push_ok"
    assert "alice" in context.baseline_profile.direct_push_authors
    findings = detect_findings(timeline, context)
    commit_findings = [
        f
        for f in findings
        if f.metric_id == "irregular_commits"
        and f.title == "Commit without usual integration path"
    ]
    assert commit_findings == []


def test_irregular_commits_direct_push_flags_new_author():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    baseline = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_commit",
                {"sha": "aaa111111111111111111111111111111111111111", "author_login": "alice"},
                baseline,
            ),
            _row(
                "github_commit",
                {
                    "sha": "ccc333333333333333333333333333333333333333",
                    "author_login": "attacker",
                },
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    commit_findings = [
        f
        for f in findings
        if f.metric_id == "irregular_commits"
        and f.title == "Commit without usual integration path"
    ]
    assert len(commit_findings) == 1
    assert "attacker" in "\n".join(commit_findings[0].evidence)


def test_irregular_commits_flags_null_login_under_direct_push():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    baseline = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    malicious_sha = "acac5a9854650c4ae2883c4740bf87d34120c038"
    timeline = load_timeline(
        [
            _row(
                "github_commit",
                {"sha": "aaa111111111111111111111111111111111111111", "author_login": "alice"},
                baseline,
            ),
            _row(
                "github_commit",
                {
                    "sha": malicious_sha,
                    "author_login": None,
                    "committer_login": None,
                    "author_email": "build-system@noreply.dev",
                },
                recent,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    commit_findings = [
        f
        for f in findings
        if f.metric_id == "irregular_commits"
        and f.title == "Commit without usual integration path"
    ]
    assert len(commit_findings) == 1
    evidence = "\n".join(commit_findings[0].evidence)
    assert "unlinked author" in evidence
    assert malicious_sha[:8] in evidence


def test_onboarding_uses_nonzero_baseline_when_most_prs_store_zero_reviews():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    rows = [
        _row(
            "github_pull_request",
            {
                "author_login": "alice",
                "merged_by_login": "alice",
                "merged_at": old,
                "number": 1,
                "state": "closed",
                "review_comment_count": 10,
                "review_count": 3,
            },
            old,
        ),
    ]
    for i in range(2, 7):
        rows.append(
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": old,
                    "number": i,
                    "state": "closed",
                    "review_comment_count": 10,
                    "review_count": 3,
                },
                old,
            )
        )
    for i in range(7, 17):
        rows.append(
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": old,
                    "number": i,
                    "state": "closed",
                    "review_comment_count": 0,
                    "review_count": 0,
                },
                old,
            )
        )
    rows.append(
        _row(
            "github_pull_request",
            {
                "author_login": "newbie",
                "merged_by_login": "reviewer",
                "merged_at": recent,
                "number": 99,
                "state": "closed",
                "review_comment_count": 2,
                "review_count": 3,
            },
            recent,
        )
    )
    timeline = load_timeline(rows)
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=now,
    )
    assert context.baseline_profile.pr_review.median_review_comments == 10.0
    onboarding = [
        f for f in detect_findings(timeline, context) if f.metric_id == "onboarding"
    ]
    assert len(onboarding) == 1
    assert "newbie" in onboarding[0].evidence[0]


def test_overall_status():
    assert overall_status([]) == "ok"
    assert (
        overall_status(
            [
                Finding(
                    metric_id="x",
                    metric_label="Test",
                    title="t",
                    summary="s",
                )
            ]
        )
        == "findings"
    )
