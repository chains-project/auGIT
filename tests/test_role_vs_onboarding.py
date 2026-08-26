from datetime import UTC, datetime, timedelta

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.timeline import load_timeline
from augit.analysis.trust_signals import detect_findings


def _row(event_type: str, payload: dict, source_timestamp: str) -> dict:
    return {
        "event_type": event_type,
        "category": "contributor",
        "payload": payload,
        "observed_at": datetime.now(UTC),
        "source_timestamp": source_timestamp,
    }


def test_new_release_author_is_release_publisher_signal_not_onboarding():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = load_timeline(
        [
            _row(
                "github_release",
                {"tag_name": "v0.1", "author_login": "alice", "published_at": old},
                old,
            ),
            _row(
                "github_release",
                {
                    "tag_name": "v4.0",
                    "author_login": "right9ctrl",
                    "published_at": recent,
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
    release_publishers = [
        f for f in findings if f.metric_id == "unverified_release_publishers"
    ]
    onboarding = [f for f in findings if f.metric_id == "onboarding"]
    assert release_publishers
    assert any("right9ctrl" in e for e in release_publishers[0].evidence)
    assert not any("right9ctrl" in e for f in onboarding for e in f.evidence)


def test_thin_review_new_author_is_onboarding_not_role_change():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")

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
                    "review_comment_count": 8,
                    "review_count": 2,
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


def test_first_direct_push_is_role_change_once_and_still_irregular():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent1 = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    recent2 = (now - timedelta(days=4)).isoformat().replace("+00:00", "Z")

    timeline = load_timeline(
        [
            _row(
                "github_commit",
                {
                    "sha": "aaaaaaaa",
                    "author_login": "alice",
                    "committed_at": old,
                    "message": "baseline",
                },
                old,
            ),
            _row(
                "github_commit",
                {
                    "sha": "bbbbbbbb",
                    "author_login": "right9ctrl",
                    "committed_at": recent1,
                    "message": "first push",
                },
                recent1,
            ),
            _row(
                "github_commit",
                {
                    "sha": "cccccccc",
                    "author_login": "right9ctrl",
                    "committed_at": recent2,
                    "message": "second push",
                },
                recent2,
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
    role = [f for f in findings if f.metric_id == "role_changes"]
    irregular = [f for f in findings if f.metric_id == "irregular_commits"]
    assert len(role) == 1
    role_evidence = [e for e in role[0].evidence if "right9ctrl" in e]
    assert len(role_evidence) == 1
    assert "first direct push" in role_evidence[0]
    assert irregular
    assert sum(1 for e in irregular[0].evidence if "right9ctrl" in e) >= 2


def test_known_merger_first_direct_push_is_role_and_irregular():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")

    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": old,
                    "merge_commit_sha": "deadbeef",
                    "number": 1,
                    "state": "closed",
                    "review_comment_count": 2,
                    "review_count": 1,
                },
                old,
            ),
            _row(
                "github_commit",
                {
                    "sha": "deadbeef",
                    "author_login": "alice",
                    "committed_at": old,
                    "message": "merge commit",
                },
                old,
            ),
            _row(
                "github_commit",
                {
                    "sha": "ffffffff",
                    "author_login": "alice",
                    "committed_at": recent,
                    "message": "first direct push by known merger",
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
    role = [f for f in findings if f.metric_id == "role_changes"]
    irregular = [f for f in findings if f.metric_id == "irregular_commits"]
    assert role
    assert any("alice" in e and "first direct push" in e for e in role[0].evidence)
    assert irregular
    assert any("alice" in e for e in irregular[0].evidence)
