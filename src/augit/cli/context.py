import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection, OperationalError
from typing import TYPE_CHECKING

import typer

from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import RepoKey
from augit.util import utc_now

if TYPE_CHECKING:
    from augit.store import EventStore

ENV_DB = "SSC_AUDIT_DB"


def parse_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def now():
    return utc_now()


def repo_key(repo: str, provider: str) -> RepoKey:
    if provider == "github":
        return github_repo_key(repo)
    return RepoKey(canonical_url=repo, provider=provider)


@dataclass
class AppContext:
    db_path: Path | None = None
    _conn: Connection | None = field(default=None, repr=False)
    _store: EventStore | None = field(default=None, repr=False)

    @classmethod
    def from_option(cls, db: Path | None) -> AppContext:
        if db is not None:
            return cls(db_path=db)
        env = os.environ.get(ENV_DB)
        if env:
            return cls(db_path=Path(env))
        return cls(db_path=None)

    def require_db_path(self) -> Path:
        if self.db_path is None:
            raise typer.BadParameter(
                f"Database path required: pass --db PATH or set {ENV_DB}"
            )
        return self.db_path

    @property
    def conn(self) -> Connection:
        path = self.require_db_path()
        if self._conn is None:
            try:
                self._conn = connect(DbConfig(path=path))
                migrate(self._conn)
            except OperationalError as exc:
                # Convert low-level SQLite operational errors into a user-facing CLI error.
                # This also keeps CLI tests stable in environments where a default DB path
                # may be set but temporarily locked.
                raise typer.BadParameter(
                    "Database could not be opened (possibly locked). "
                    "Pass --db PATH or set SSC_AUDIT_DB to a writable, unlocked database."
                ) from exc
        return self._conn

    @property
    def store(self) -> EventStore:
        if self._store is None:
            from augit.store import EventStore

            self._store = EventStore(self.conn)
        return self._store
