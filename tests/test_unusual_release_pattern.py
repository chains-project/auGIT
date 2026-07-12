from datetime import UTC, datetime, timedelta

from augit.analysis.profile import resolve_audit_context
from augit.analysis.timeline import load_timeline
from augit.analysis.trust_signals import detect_findings


def _row(event_type: str, payload: dict, ts: str) -> dict:
    return {
        "event_type": event_type,
        "category": "release",
        "payload": payload,
        "observed_at": datetime.now(UTC),
        "source_timestamp": ts,
    }


def test_release_burst_includes_release_count():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    d1 = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    d2 = (now - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    d3 = (now - timedelta(days=6)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_release",
                {
                    "tag_name": "v1.0.0",
                    "author_login": "alice",
                    "published_at": d1,
                },
                d1,
            ),
            _row(
                "github_release",
                {
                    "tag_name": "v1.0.1",
                    "author_login": "alice",
                    "published_at": d2,
                },
                d2,
            ),
            _row(
                "github_release",
                {
                    "tag_name": "v1.0.2",
                    "author_login": "alice",
                    "published_at": d3,
                },
                d3,
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=90,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    bursts = [
        f
        for f in findings
        if f.metric_id == "unusual_release_pattern" and f.title == "Release burst"
    ]
    assert len(bursts) == 1
    assert "3 releases across 1 burst within 7 days" in bursts[0].summary
    assert len(bursts[0].evidence) == 1
    assert "(3 releases)" in bursts[0].evidence[0]


def test_release_burst_groups_multiple_bursts_per_author():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    bursts = [
        (now - timedelta(days=60), "v1.0.0"),
        (now - timedelta(days=58), "v1.0.1"),
        (now - timedelta(days=20), "v1.1.0"),
        (now - timedelta(days=18), "v1.1.1"),
    ]
    rows = []
    for dt, tag in bursts:
        ts = dt.isoformat().replace("+00:00", "Z")
        rows.append(
            _row(
                "github_release",
                {
                    "tag_name": tag,
                    "author_login": "alice",
                    "published_at": ts,
                },
                ts,
            )
        )
    timeline = load_timeline(rows)
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=90,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    burst_findings = [
        f
        for f in findings
        if f.metric_id == "unusual_release_pattern" and f.title == "Release burst"
    ]
    assert len(burst_findings) == 1
    assert "4 releases across 2 bursts within 7 days" in burst_findings[0].summary
    assert len(burst_findings[0].evidence) == 2
