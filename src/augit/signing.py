"""Helpers for Git commit signature metadata from GitHub verification objects."""

from __future__ import annotations

import base64
import struct

# GitHub web UI / squash-merge signing key (https://github.com/web-flow.gpg).
GITHUB_PLATFORM_OPENPGP_KEY_IDS = frozenset(
    {
        "B5690EEEBB952194",
    }
)


def looks_like_signed_commit_payload(value: str | None) -> bool:
    """Detect legacy rows that stored verification.payload as signer_key_id."""
    if not value:
        return False
    head = value.lstrip()
    return head.startswith("tree ") or head.startswith("object ")


def is_platform_signing_key_id(key_id: str | None) -> bool:
    if not key_id:
        return False
    normalized = key_id.strip().upper().removeprefix("0X")
    return normalized in GITHUB_PLATFORM_OPENPGP_KEY_IDS


def normalize_signing_key_id(key_id: str | None) -> str | None:
    if not key_id or looks_like_signed_commit_payload(key_id):
        return None
    normalized = key_id.strip().upper().removeprefix("0X")
    if not normalized:
        return None
    if is_platform_signing_key_id(normalized):
        return None
    return normalized


def extract_openpgp_signer_key_id(signature: str | None) -> str | None:
    """Return the 8-byte OpenPGP issuer key ID from an armored detached signature."""
    if not signature or not signature.strip():
        return None
    try:
        data = _decode_openpgp_armor(signature)
    except (ValueError, struct.error, IndexError):
        return None
    return _issuer_key_id_from_openpgp_packets(data)


def signing_key_id_from_verification(verification: dict | None) -> str | None:
    if not verification or not verification.get("verified"):
        return None
    key_id = extract_openpgp_signer_key_id(verification.get("signature"))
    return normalize_signing_key_id(key_id)


def _decode_openpgp_armor(signature: str) -> bytes:
    lines = [
        line.strip()
        for line in signature.strip().splitlines()
        if line.strip() and not line.startswith("-----")
    ]
    if not lines:
        raise ValueError("empty armored signature")
    return base64.b64decode("".join(lines))


def _issuer_key_id_from_openpgp_packets(data: bytes) -> str | None:
    offset = 0
    while offset < len(data):
        header = data[offset]
        offset += 1
        tag = header & 0x3F
        length, offset = _read_openpgp_packet_length(data, offset, header=header)
        if length is None:
            return None
        if offset + length > len(data):
            return None
        body = data[offset : offset + length]
        offset += length
        if tag != 2 or not body:
            continue
        key_id = _issuer_key_id_from_signature_packet(body)
        if key_id:
            return key_id
    return None


def _read_openpgp_packet_length(
    data: bytes,
    offset: int,
    *,
    header: int,
) -> tuple[int | None, int]:
    if not (header & 0x80):
        length_type = header & 0x03
        if length_type == 0:
            if offset >= len(data):
                return None, offset
            return data[offset], offset + 1
        if length_type == 1:
            if offset + 2 > len(data):
                return None, offset
            return struct.unpack(">H", data[offset : offset + 2])[0], offset + 2
        if length_type == 2:
            if offset + 4 > len(data):
                return None, offset
            return struct.unpack(">I", data[offset : offset + 4])[0], offset + 4
        return None, offset

    if offset >= len(data):
        return None, offset
    first = data[offset]
    offset += 1
    if first < 192:
        return first, offset
    if first < 224:
        if offset >= len(data):
            return None, offset
        second = data[offset]
        offset += 1
        return ((first - 192) << 8) + second + 192, offset
    if first < 255:
        return None, offset
    if offset + 4 > len(data):
        return None, offset
    length = struct.unpack(">I", data[offset : offset + 4])[0]
    return length, offset + 4


def _issuer_key_id_from_signature_packet(body: bytes) -> str | None:
    if not body or body[0] != 4:
        return None
    offset = 1 + 1 + 1 + 1  # version, type, pk algo, hash algo
    if offset + 2 > len(body):
        return None
    hashed_len = struct.unpack(">H", body[offset : offset + 2])[0]
    offset += 2
    key_id = _scan_openpgp_subpackets(body, offset, hashed_len)
    if key_id:
        return key_id
    offset += hashed_len
    if offset + 2 > len(body):
        return None
    unhashed_len = struct.unpack(">H", body[offset : offset + 2])[0]
    offset += 2
    return _scan_openpgp_subpackets(body, offset, unhashed_len)


def _scan_openpgp_subpackets(body: bytes, offset: int, length: int) -> str | None:
    end = offset + length
    while offset < end:
        if offset >= len(body):
            break
        subpacket_len = body[offset]
        offset += 1
        if subpacket_len >= 192:
            if subpacket_len < 255:
                if offset >= len(body):
                    break
                subpacket_len = ((subpacket_len - 192) << 8) + body[offset] + 192
                offset += 1
            else:
                if offset + 3 > len(body):
                    break
                subpacket_len = struct.unpack(">I", b"\x00" + body[offset : offset + 3])[0]
                offset += 3
        if offset >= len(body):
            break
        subpacket_type = body[offset]
        offset += 1
        if subpacket_len < 1:
            break
        subpacket_data = body[offset : offset + subpacket_len - 1]
        if len(subpacket_data) < subpacket_len - 1:
            break
        offset += subpacket_len - 1
        if subpacket_type in (9, 16) and len(subpacket_data) >= 8:
            return subpacket_data[-8:].hex().upper()
    return None
