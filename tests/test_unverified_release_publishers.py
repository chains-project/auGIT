from datetime import UTC, datetime, timedelta

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.trust_signals import detect_findings
from conftest import make_timeline, timeline_row


def test_new_github_release_publisher_is_flagged():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "github_release",
                {"tag_name": "v0.1", "author_login": "alice", "published_at": old},
                source_timestamp=old,
            ),
            timeline_row(
                "github_release",
                {
                    "tag_name": "v2.0",
                    "author_login": "right9ctrl",
                    "published_at": recent,
                },
                source_timestamp=recent,
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
    matches = [f for f in findings if f.metric_id == "unverified_release_publishers"]
    assert len(matches) == 1
    assert any("right9ctrl" in e for e in matches[0].evidence)


def test_known_release_publisher_not_flagged():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "github_release",
                {"tag_name": "v0.1", "author_login": "alice", "published_at": old},
                source_timestamp=old,
            ),
            timeline_row(
                "github_release",
                {"tag_name": "v1.0", "author_login": "alice", "published_at": recent},
                source_timestamp=recent,
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
    matches = [f for f in findings if f.metric_id == "unverified_release_publishers"]
    assert not matches


def test_new_registry_uploader_is_flagged():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "pypi_release_version",
                {
                    "version": "1.0.0",
                    "published_at": old,
                    "uploaders": ["alice"],
                },
                category="registry",
                source_timestamp=old,
            ),
            timeline_row(
                "pypi_release_version",
                {
                    "version": "2.0.0",
                    "published_at": recent,
                    "uploaders": ["mallory"],
                },
                category="registry",
                source_timestamp=recent,
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
    matches = [f for f in findings if f.metric_id == "unverified_release_publishers"]
    assert len(matches) == 1
    assert any("mallory" in e for e in matches[0].evidence)
