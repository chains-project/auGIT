"""Normalize and compare Git tags / registry version labels."""

from __future__ import annotations

import re


def normalize_version_label(label: str) -> str:
    """Normalize a Git tag or registry version for equality checks.

    Treats optional leading ``v``/``V`` as equivalent when it prefixes a digit,
    so ``2.34.2`` matches ``v2.34.2``.
    """
    s = label.strip()
    if len(s) >= 2 and s[0] in "vV" and s[1].isdigit():
        return s[1:]
    return s


def version_labels_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return normalize_version_label(a) == normalize_version_label(b)


def has_matching_version_label(needle: str | None, haystack: list[str] | set[str]) -> bool:
    if not needle:
        return False
    target = normalize_version_label(needle)
    return any(normalize_version_label(item) == target for item in haystack if item)


def parse_version_tuple(label: str | None) -> tuple[int, int, int] | None:
    """Parse a leading major.minor.patch triple from a tag or version label."""
    if not label:
        return None
    s = normalize_version_label(label)
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", s)
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )
