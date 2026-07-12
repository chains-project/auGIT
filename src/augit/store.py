import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from augit.models import EventIn, RepoKey, RunMode


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().isoformat()


def _dt_from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditState:
    checkpoint_at: datetime | None
    profile_json: str | None
    last_report_at: datetime | None
    last_report_status: str | None


@dataclass(frozen=True)
class EventStore:
    conn: sqlite3.Connection
    tool_version: str = "0.1.0"

    def ensure_repo(self, repo: RepoKey) -> int:
        created_at = _dt_to_iso(_now())
        self.conn.execute(
            """
            INSERT OR IGNORE INTO repositories(canonical_url, provider, created_at)
            VALUES (?, ?, ?);
            """,
            (repo.canonical_url, repo.provider, created_at),
        )
        row = self.conn.execute(
            "SELECT id FROM repositories WHERE canonical_url=? AND provider=?;",
            (repo.canonical_url, repo.provider),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def start_run(self, repo_id: int, mode: RunMode) -> int:
        started = _dt_to_iso(_now())
        cur = self.conn.execute(
            """
            INSERT INTO runs(repo_id, run_started_at, run_finished_at, mode, tool_version)
            VALUES (?, ?, NULL, ?, ?);
            """,
            (repo_id, started, mode, self.tool_version),
        )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int) -> None:
        finished = _dt_to_iso(_now())
        self.conn.execute(
            "UPDATE runs SET run_finished_at=? WHERE id=?;",
            (finished, run_id),
        )
        self.conn.commit()

    def append_event(self, run_id: int, event: EventIn) -> int | None:
        repo_id = self.ensure_repo(event.repo)
        payload_json = _stable_json(event.payload)
        payload_sha = _sha256_text(payload_json)

        if event.source_event_id is None:
            cur = self.conn.execute(
                """
                INSERT INTO events(
                  repo_id, run_id, category, event_type, source,
                  source_event_id, source_timestamp, observed_at,
                  payload_json, payload_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    repo_id,
                    run_id,
                    event.category,
                    event.event_type,
                    event.source,
                    None,
                    _dt_to_iso(event.source_timestamp),
                    _dt_to_iso(event.observed_at) or _dt_to_iso(_now()),
                    payload_json,
                    payload_sha,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

        existing = self.conn.execute(
            """
            SELECT id, payload_sha256 FROM events
            WHERE repo_id=? AND source=? AND source_event_id=?;
            """,
            (repo_id, event.source, event.source_event_id),
        ).fetchone()
        if existing is None:
            cur = self.conn.execute(
                """
                INSERT INTO events(
                  repo_id, run_id, category, event_type, source,
                  source_event_id, source_timestamp, observed_at,
                  payload_json, payload_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    repo_id,
                    run_id,
                    event.category,
                    event.event_type,
                    event.source,
                    event.source_event_id,
                    _dt_to_iso(event.source_timestamp),
                    _dt_to_iso(event.observed_at) or _dt_to_iso(_now()),
                    payload_json,
                    payload_sha,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

        if existing["payload_sha256"] == payload_sha:
            return None

        self.conn.execute(
            """
            UPDATE events SET
              run_id=?,
              category=?,
              event_type=?,
              source_timestamp=?,
              observed_at=?,
              payload_json=?,
              payload_sha256=?
            WHERE id=?;
            """,
            (
                run_id,
                event.category,
                event.event_type,
                _dt_to_iso(event.source_timestamp),
                _dt_to_iso(event.observed_at) or _dt_to_iso(_now()),
                payload_json,
                payload_sha,
                existing["id"],
            ),
        )
        self.conn.commit()
        return None

    def append_events(self, run_id: int, events: Iterable[EventIn]) -> int:
        inserted = 0
        for e in events:
            if self.append_event(run_id, e) is not None:
                inserted += 1
        return inserted

    def set_cursor(self, repo: RepoKey, source: str, cursor: dict[str, Any]) -> None:
        repo_id = self.ensure_repo(repo)
        updated_at = _dt_to_iso(_now())
        cursor_json = _stable_json(cursor)
        self.conn.execute(
            """
            INSERT INTO cursors(repo_id, source, cursor_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(repo_id, source) DO UPDATE SET
              cursor_json=excluded.cursor_json,
              updated_at=excluded.updated_at;
            """,
            (repo_id, source, cursor_json, updated_at),
        )
        self.conn.commit()

    def get_cursor(self, repo: RepoKey, source: str) -> dict[str, Any] | None:
        repo_id = self.ensure_repo(repo)
        row = self.conn.execute(
            "SELECT cursor_json FROM cursors WHERE repo_id=? AND source=?;",
            (repo_id, source),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["cursor_json"])

    def iter_events_for_repo(
        self,
        repo: RepoKey,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Iterable[dict[str, Any]]:
        repo_id = self.ensure_repo(repo)
        params: list[Any] = [repo_id]
        where = ["repo_id=?"]
        if since is not None:
            where.append("observed_at >= ?")
            params.append(_dt_to_iso(since))
        if until is not None:
            where.append("observed_at <= ?")
            params.append(_dt_to_iso(until))

        sql = f"""
        SELECT
          id, repo_id, run_id, category, event_type, source, source_event_id,
          source_timestamp, observed_at, payload_json
        FROM events
        WHERE {" AND ".join(where)}
        ORDER BY observed_at ASC, id ASC;
        """
        for row in self.conn.execute(sql, params):
            yield {
                "id": int(row["id"]),
                "repo_id": int(row["repo_id"]),
                "run_id": int(row["run_id"]),
                "category": row["category"],
                "event_type": row["event_type"],
                "source": row["source"],
                "source_event_id": row["source_event_id"],
                "source_timestamp": _dt_from_iso(row["source_timestamp"]),
                "observed_at": _dt_from_iso(row["observed_at"]),
                "payload": json.loads(row["payload_json"]),
            }

    def get_latest_integrity_refetch(self, repo: RepoKey) -> dict[str, Any] | None:
        repo_id = self.ensure_repo(repo)
        row = self.conn.execute(
            """
            SELECT id, refetched_at, subjects_json, summary_json
            FROM integrity_refetches
            WHERE repo_id=?
            ORDER BY refetched_at DESC, id DESC
            LIMIT 1;
            """,
            (repo_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "refetched_at": _dt_from_iso(row["refetched_at"]),
            "subjects": json.loads(row["subjects_json"]),
            "summary": json.loads(row["summary_json"]),
        }

    def insert_integrity_refetch(
        self,
        repo: RepoKey,
        run_id: int,
        refetched_at: datetime,
        subjects: dict[str, Any],
        summary: dict[str, Any],
    ) -> int:
        repo_id = self.ensure_repo(repo)
        cur = self.conn.execute(
            """
            INSERT INTO integrity_refetches(repo_id, run_id, refetched_at, subjects_json, summary_json)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                repo_id,
                run_id,
                _dt_to_iso(refetched_at),
                _stable_json(subjects),
                _stable_json(summary),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_package_link(
        self,
        package_key: RepoKey,
        github_key: RepoKey,
        *,
        source_field: str,
        raw_url: str,
    ) -> None:
        package_repo_id = self.ensure_repo(package_key)
        github_repo_id = self.ensure_repo(github_key)
        linked_at = _dt_to_iso(_now())
        self.conn.execute(
            """
            INSERT INTO package_links(package_repo_id, github_repo_id, source_field, raw_url, linked_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(package_repo_id) DO UPDATE SET
              github_repo_id=excluded.github_repo_id,
              source_field=excluded.source_field,
              raw_url=excluded.raw_url,
              linked_at=excluded.linked_at;
            """,
            (package_repo_id, github_repo_id, source_field, raw_url, linked_at),
        )
        self.conn.commit()

    def get_package_link(self, package_key: RepoKey) -> dict[str, Any] | None:
        package_repo_id = self.ensure_repo(package_key)
        row = self.conn.execute(
            """
            SELECT pl.source_field, pl.raw_url, pl.linked_at,
                   r.canonical_url AS github_canonical_url
            FROM package_links pl
            JOIN repositories r ON r.id = pl.github_repo_id
            WHERE pl.package_repo_id=?;
            """,
            (package_repo_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "source_field": row["source_field"],
            "raw_url": row["raw_url"],
            "linked_at": _dt_from_iso(row["linked_at"]),
            "github_canonical_url": row["github_canonical_url"],
        }

    def get_github_for_package(self, package_key: RepoKey) -> RepoKey | None:
        link = self.get_package_link(package_key)
        if link is None:
            return None
        return RepoKey(canonical_url=link["github_canonical_url"], provider="github")

    def get_audit_state(self, repo: RepoKey) -> AuditState | None:
        repo_id = self.ensure_repo(repo)
        row = self.conn.execute(
            """
            SELECT checkpoint_at, profile_json, last_report_at, last_report_status
            FROM repo_audit_state
            WHERE repo_id=?;
            """,
            (repo_id,),
        ).fetchone()
        if row is None:
            return None
        return AuditState(
            checkpoint_at=_dt_from_iso(row["checkpoint_at"]),
            profile_json=row["profile_json"],
            last_report_at=_dt_from_iso(row["last_report_at"]),
            last_report_status=row["last_report_status"],
        )

    def save_report_meta(
        self,
        repo: RepoKey,
        *,
        report_at: datetime,
        status: str,
    ) -> None:
        repo_id = self.ensure_repo(repo)
        self.conn.execute(
            """
            INSERT INTO repo_audit_state(repo_id, last_report_at, last_report_status)
            VALUES (?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
              last_report_at=excluded.last_report_at,
              last_report_status=excluded.last_report_status;
            """,
            (repo_id, _dt_to_iso(report_at), status),
        )
        self.conn.commit()

    def save_checkpoint(
        self,
        repo: RepoKey,
        *,
        checkpoint_at: datetime,
        profile_json: str,
        report_status: str,
    ) -> None:
        repo_id = self.ensure_repo(repo)
        now = _dt_to_iso(checkpoint_at)
        self.conn.execute(
            """
            INSERT INTO repo_audit_state(
              repo_id, checkpoint_at, profile_json, last_report_at, last_report_status
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
              checkpoint_at=excluded.checkpoint_at,
              profile_json=excluded.profile_json,
              last_report_at=excluded.last_report_at,
              last_report_status=excluded.last_report_status;
            """,
            (repo_id, now, profile_json, now, report_status),
        )
        self.conn.commit()
