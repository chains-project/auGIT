from pathlib import Path
from sqlite3 import OperationalError

import typer

from augit.cli.context import AppContext, parse_dt, repo_key
from augit.export import export_events_jsonl


def register_export(app: typer.Typer) -> None:
    @app.command("export", help="Export audit events to JSONL")
    def export_events(
        ctx: typer.Context,
        repo: str = typer.Argument(
            ...,
            help="Repository id (owner/repo, package name, or GAV depending on provider)",
        ),
        out: Path = typer.Option(..., "--out", help="Output JSONL file path"),
        provider: str = typer.Option("github", "--provider"),
        since: str | None = typer.Option(None, "--since"),
        until: str | None = typer.Option(None, "--until"),
    ) -> None:
        try:
            app_ctx: AppContext = ctx.obj
            store = app_ctx.store
            repo_key_val = repo_key(repo, provider)
            count = export_events_jsonl(
                store,
                repo_key_val,
                out,
                since=parse_dt(since),
                until=parse_dt(until),
            )
            typer.echo(f"exported={count} to={out}")
        except OperationalError as exc:
            raise typer.BadParameter(
                "Database could not be accessed (possibly locked). "
                "Pass --db PATH or set SSC_AUDIT_DB."
            ) from exc
