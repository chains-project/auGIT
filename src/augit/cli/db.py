from pathlib import Path

import typer

from augit.db import DbConfig, connect
from augit.migrate import migrate

db_app = typer.Typer(help="Database setup")


@db_app.command("init")
def db_init(
    path: Path = typer.Option(..., "--path", help="Path to SQLite DB file"),
) -> None:
    conn = connect(DbConfig(path=path))
    migrate(conn)
    typer.echo(f"initialized db at {path}")
