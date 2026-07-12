from datetime import UTC, datetime

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.trust_signals import detect_findings
from conftest import make_timeline, timeline_row


def test_repo_moved_integrity_event_surfaces_as_ownership_finding():
    observed = datetime(2026, 3, 1, tzinfo=UTC)
    timeline = make_timeline(
        [
            timeline_row(
                "integrity_drift",
                {
                    "subtype": "repo_moved",
                    "severity": "high",
                    "expected": {"canonical_url": "https://github.com/org/old"},
                    "observed": {"canonical_url": "https://github.com/org/new"},
                },
                category="integrity",
                observed_at=observed,
                source_timestamp=observed.isoformat().replace("+00:00", "Z"),
                source="refetch_compare",
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=observed,
    )
    findings = detect_findings(timeline, context)
    matches = [f for f in findings if f.metric_id == "ownership_changes"]
    assert len(matches) == 1
    assert "identity changed" in matches[0].title.lower()


def test_no_ownership_finding_without_repo_moved():
    observed = datetime(2026, 3, 1, tzinfo=UTC)
    timeline = make_timeline(
        [
            timeline_row(
                "integrity_drift",
                {
                    "subtype": "tag_retargeted",
                    "severity": "high",
                },
                category="integrity",
                observed_at=observed,
                source="refetch_compare",
            ),
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=DEFAULT_TAIL_DAYS,
        as_of=observed,
    )
    findings = detect_findings(timeline, context)
    matches = [f for f in findings if f.metric_id == "ownership_changes"]
    assert not matches
