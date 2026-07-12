import sqlite3
from importlib import resources

from augit.constants import SCHEMA_VERSION


def migrate(conn: sqlite3.Connection) -> None:
    current = int(conn.execute("PRAGMA user_version;").fetchone()[0])
    if current >= SCHEMA_VERSION:
        return

    # v1
    if current < 1:
        sql = (
            resources.files("augit")
            .joinpath("migrations/001_init.sql")
            .read_text(encoding="utf-8")
        )
        conn.executescript(sql)
        conn.execute("PRAGMA user_version=1;")

    if current < 2:
        sql = (
            resources.files("augit")
            .joinpath("migrations/002_package_links.sql")
            .read_text(encoding="utf-8")
        )
        conn.executescript(sql)
        conn.execute("PRAGMA user_version=2;")

    if current < 3:
        sql = (
            resources.files("augit")
            .joinpath("migrations/003_repo_audit_state.sql")
            .read_text(encoding="utf-8")
        )
        conn.executescript(sql)
        conn.execute("PRAGMA user_version=3;")

    conn.commit()
