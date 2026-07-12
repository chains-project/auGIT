from datetime import datetime
from pathlib import Path

import typer

from augit.analysis.html_render import render_html
from augit.analysis.report_builder import ReportOptions, build_trust_report
from augit.cli.context import AppContext, repo_key
from augit.collectors.github_api import github_repo_key


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def register_report(app: typer.Typer) -> None:
    @app.command("report", help="Generate an HTML trust report from the audit log")
    def report_cmd(
        ctx: typer.Context,
        repo: str = typer.Argument(..., help="owner/repo, package name, or GAV"),
        out: Path = typer.Option(..., "--out", help="Output HTML file"),
        provider: str = typer.Option(
            "github",
            "--provider",
            help="github (default), pypi, or maven",
        ),
        mode: str = typer.Option(
            "initial",
            "--mode",
            help="initial (default) or reaudit",
        ),
        tail_days: int = typer.Option(
            90,
            "--tail-days",
            help="Compare window length for initial audits",
        ),
        as_of: str | None = typer.Option(
            None,
            "--as-of",
            help="ISO timestamp for compare window end (retrospective audits)",
        ),
        acknowledge: bool = typer.Option(
            False,
            "--acknowledge",
            help="Store checkpoint and profile snapshot after generating the report",
        ),
    ) -> None:
        app_ctx: AppContext = ctx.obj
        store = app_ctx.store
        if provider == "github":
            repo_key_val = github_repo_key(repo)
        else:
            repo_key_val = repo_key(repo, provider)

        if mode not in ("initial", "reaudit"):
            raise typer.BadParameter("mode must be initial or reaudit")

        options = ReportOptions(
            mode=mode,  # type: ignore[arg-type]
            tail_days=tail_days,
            as_of=_parse_as_of(as_of),
            acknowledge=acknowledge,
        )
        trust_report = build_trust_report(store, repo_key_val, options=options)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(trust_report), encoding="utf-8")
        typer.echo(
            f"report written to {out} status={trust_report.status} "
            f"mode={trust_report.audit_mode} "
            f"findings={len(trust_report.findings)} events={trust_report.total_events}"
        )
        if acknowledge:
            typer.echo("checkpoint saved")
