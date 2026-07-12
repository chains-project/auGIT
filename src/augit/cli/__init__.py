from pathlib import Path

import typer

from augit.cli.check import register_check
from augit.cli.collect import collect_app
from augit.cli.context import ENV_DB, AppContext
from augit.cli.db import db_app
from augit.cli.export_cmd import register_export
from augit.cli.link import link_app
from augit.cli.report_cmd import register_report

app = typer.Typer(
    add_completion=False,
    help="Append-only supply-chain audit log for GitHub, PyPI, and Maven.",
    rich_markup_mode="rich",
)

app.add_typer(db_app, name="db")
app.add_typer(collect_app, name="collect")
app.add_typer(link_app, name="link")

register_check(app)
register_export(app)
register_report(app)


@app.callback()
def main(
    ctx: typer.Context,
    db: Path | None = typer.Option(
        None,
        "--db",
        help=f"SQLite database path (or set {ENV_DB})",
        envvar=ENV_DB,
    ),
) -> None:
    """Supply-chain audit log CLI."""
    ctx.ensure_object(dict)
    ctx.obj = AppContext.from_option(db)
