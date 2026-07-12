from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from augit.analysis.timeline import RepoTimeline, load_timeline
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.store import EventStore


def now_utc() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def db_store(tmp_path) -> Iterator[EventStore]:
    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)
    try:
        yield store
    finally:
        conn.close()


def timeline_row(
    event_type: str,
    payload: dict,
    *,
    category: str = "contributor",
    observed_at: datetime | None = None,
    source_timestamp: str | None = None,
    source: str | None = None,
) -> dict:
    row: dict = {
        "event_type": event_type,
        "category": category,
        "payload": payload,
        "observed_at": observed_at or now_utc(),
    }
    if source_timestamp is not None:
        row["source_timestamp"] = source_timestamp
    if source is not None:
        row["source"] = source
    return row


def make_timeline(rows: list[dict]) -> RepoTimeline:
    return load_timeline(rows)
