import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbConfig:
    path: Path


def connect(config: DbConfig) -> sqlite3.Connection:
    config.path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.path)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    # Improve integrity and concurrency for a single-writer workload.
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
