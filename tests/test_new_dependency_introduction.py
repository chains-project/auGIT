from datetime import UTC, datetime, timedelta

from augit.analysis.profile import DEFAULT_TAIL_DAYS, resolve_audit_context
from augit.analysis.trust_signals import detect_findings
from conftest import make_timeline, timeline_row


def test_new_dependency_in_compare_window_is_flagged():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "dependency_manifest_change",
                {
                    "added": ["lodash"],
                    "author_login": "alice",
                    "pr_number": 1,
                    "commit_sha": "aaa11111",
                },
                category="dependency",
                source_timestamp=old,
            ),
            timeline_row(
                "dependency_manifest_change",
                {
                    "added": ["left-pad"],
                    "author_login": "bob",
                    "pr_number": 2,
                    "commit_sha": "bbb22222",
                },
                category="dependency",
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
    matches = [f for f in findings if f.metric_id == "new_dependency_introduction"]
    assert len(matches) == 1
    evidence = "\n".join(matches[0].evidence)
    assert "left-pad" in evidence
    assert "lodash" not in evidence
    assert "PR #2" in evidence


def test_commit_only_dependency_change_omits_pr_in_evidence():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "dependency_manifest_change",
                {
                    "added": ["flatmap-stream"],
                    "author_login": "right9ctrl",
                    "pr_number": None,
                    "commit_sha": "e3163361fed01384c986b9b4c18feb1fc42b8285",
                },
                category="dependency",
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
    matches = [f for f in findings if f.metric_id == "new_dependency_introduction"]
    assert len(matches) == 1
    evidence = "\n".join(matches[0].evidence)
    assert "flatmap-stream" in evidence
    assert "PR #" not in evidence
    assert "e3163361" in evidence


def test_baseline_dependency_not_flagged_in_compare_window():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "dependency_manifest_change",
                {
                    "added": ["lodash"],
                    "author_login": "alice",
                    "pr_number": 1,
                },
                category="dependency",
                source_timestamp=old,
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
    matches = [f for f in findings if f.metric_id == "new_dependency_introduction"]
    assert not matches


def test_registry_versions_without_manifest_diffs_emit_info_finding():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    recent = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")

    timeline = make_timeline(
        [
            timeline_row(
                "pypi_release_version",
                {"version": "1.0.0", "published_at": recent},
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
    matches = [f for f in findings if f.metric_id == "new_dependency_introduction"]
    assert len(matches) == 1
    assert "no dependency_manifest_change" in matches[0].summary.lower()
