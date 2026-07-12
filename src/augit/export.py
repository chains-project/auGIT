import json
from datetime import datetime
from pathlib import Path
from typing import Any

from augit.constants import SCHEMA_VERSION
from augit.models import RepoKey
from augit.store import EventStore


def export_events_jsonl(
    store: EventStore,
    repo: RepoKey,
    out_path: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for row in store.iter_events_for_repo(repo, since=since, until=until):
            record: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "repo": {
                    "canonical_url": repo.canonical_url,
                    "provider": repo.provider,
                },
                "id": row["id"],
                "run_id": row["run_id"],
                "category": row["category"],
                "event_type": row["event_type"],
                "source": row["source"],
                "source_event_id": row["source_event_id"],
                "source_timestamp": row["source_timestamp"].isoformat()
                if row["source_timestamp"]
                else None,
                "observed_at": row["observed_at"].isoformat()
                if row["observed_at"]
                else None,
                "payload": row["payload"],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count
