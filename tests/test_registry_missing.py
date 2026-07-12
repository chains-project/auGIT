from datetime import UTC, datetime, timedelta

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.trust_signals import detect_findings
from conftest import make_timeline, timeline_row


def test_registry_missing_surfaces_outside_compare_window():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    observed = datetime(2026, 7, 1, tzinfo=UTC)

    timeline = make_timeline(
        [
            timeline_row(
                "pypi_project_missing",
                {
                    "name": "ctx",
                    "url": "https://pypi.org/pypi/ctx/json",
                    "http_status": 404,
                },
                category="release",
                source="registry",
                observed_at=observed,
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
    matches = [f for f in findings if f.metric_id == "registry_missing"]
    assert len(matches) == 1
    assert "404" in matches[0].evidence[0]
