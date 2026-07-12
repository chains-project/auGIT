from datetime import UTC, datetime, timedelta

from augit.analysis.profile import build_profile, resolve_audit_context
from augit.analysis.timeline import load_timeline


def _row(event_type: str, payload: dict, ts: str) -> dict:
    return {
        "event_type": event_type,
        "category": "contributor",
        "payload": payload,
        "observed_at": datetime.now(UTC),
        "source_timestamp": ts,
    }


def test_build_profile_learns_privileged_mergers():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            _row(
                "github_pull_request",
                {
                    "author_login": "alice",
                    "merged_by_login": "alice",
                    "merged_at": old,
                    "number": 1,
                },
                old,
            ),
        ]
    )
    profile = build_profile(timeline, baseline_until=now - timedelta(days=90))
    assert "alice" in profile.privileged_mergers


def test_resolve_audit_context_initial_mode():
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
                },
                old,
            ),
            _row(
                "github_release",
                {"author_login": "bob", "tag_name": "v1", "published_at": recent},
                recent,
            ),
        ]
    )
    ctx = resolve_audit_context(
        mode="initial", timeline=timeline, tail_days=90, as_of=now
    )
    assert ctx.compare_end == now
    assert ctx.compare_start == now - timedelta(days=90)
    assert "alice" in ctx.baseline_profile.privileged_mergers
