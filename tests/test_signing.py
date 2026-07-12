import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from augit.analysis.profile import resolve_audit_context
from augit.analysis.timeline import load_timeline
from augit.analysis.trust_signals import detect_findings
from augit.signing import (
    extract_openpgp_signer_key_id,
    looks_like_signed_commit_payload,
    normalize_signing_key_id,
    signing_key_id_from_verification,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "github_commit_verification.json"


def test_extract_openpgp_signer_key_id_from_github_web_flow_signature():
    verification = json.loads(_FIXTURE.read_text("utf-8"))
    assert (
        extract_openpgp_signer_key_id(verification["signature"]) == "B5690EEEBB952194"
    )
    assert signing_key_id_from_verification(verification) is None


def test_normalize_signing_key_id_filters_payload_and_platform_keys():
    assert looks_like_signed_commit_payload("tree abc\nparent def")
    assert normalize_signing_key_id("tree abc") is None
    assert normalize_signing_key_id("B5690EEEBB952194") is None
    assert normalize_signing_key_id("aabbccddeeff0011") == "AABBCCDDEEFF0011"


def test_extract_openpgp_signer_key_id_handles_truncated_packet():
    truncated = base64.b64encode(b"\x02").decode()
    signature = (
        "-----BEGIN PGP SIGNATURE-----\n"
        f"{truncated}\n"
        "-----END PGP SIGNATURE-----"
    )
    assert extract_openpgp_signer_key_id(signature) is None


def test_extract_openpgp_signer_key_id_handles_short_body():
    # Old-format length claims 5 bytes but packet ends early.
    truncated = base64.b64encode(b"\x02\x05").decode()
    signature = (
        "-----BEGIN PGP SIGNATURE-----\n"
        f"{truncated}\n"
        "-----END PGP SIGNATURE-----"
    )
    assert extract_openpgp_signer_key_id(signature) is None


def test_contributor_identity_ignores_legacy_payload_key_ids():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    payload_key = (
        "tree abcdef\nparent 123456\nauthor Alice <a@example.com> 0 +0000\n"
        "committer GitHub <noreply@github.com> 0 +0000\n\nmsg"
    )
    timeline = load_timeline(
        [
            {
                "event_type": "github_commit",
                "category": "contributor",
                "payload": {
                    "sha": "aaa",
                    "author_login": "alice",
                    "verified": True,
                    "signer_key_id": payload_key,
                },
                "observed_at": datetime.now(UTC),
                "source_timestamp": old,
            },
            {
                "event_type": "github_commit",
                "category": "contributor",
                "payload": {
                    "sha": "bbb",
                    "author_login": "alice",
                    "verified": True,
                    "signer_key_id": payload_key + "2",
                },
                "observed_at": datetime.now(UTC),
                "source_timestamp": recent,
            },
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=90,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    assert not any(f.metric_id == "contributor_identity" for f in findings)


def test_contributor_identity_flags_new_personal_key():
    now = datetime(2026, 5, 1, tzinfo=UTC)
    old = (now - timedelta(days=200)).isoformat().replace("+00:00", "Z")
    recent = (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    timeline = load_timeline(
        [
            {
                "event_type": "github_commit",
                "category": "contributor",
                "payload": {
                    "sha": "aaa",
                    "author_login": "alice",
                    "verified": True,
                    "signer_key_id": "AABBCCDDEEFF0011",
                },
                "observed_at": datetime.now(UTC),
                "source_timestamp": old,
            },
            {
                "event_type": "github_commit",
                "category": "contributor",
                "payload": {
                    "sha": "bbb",
                    "author_login": "alice",
                    "verified": True,
                    "signer_key_id": "1122334455667788",
                },
                "observed_at": datetime.now(UTC),
                "source_timestamp": recent,
            },
        ]
    )
    context = resolve_audit_context(
        mode="initial",
        timeline=timeline,
        tail_days=90,
        as_of=now,
    )
    findings = detect_findings(timeline, context)
    identity = [f for f in findings if f.metric_id == "contributor_identity"]
    assert len(identity) == 1
    assert "1122334455667788" in identity[0].evidence[0]
