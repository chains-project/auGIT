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
