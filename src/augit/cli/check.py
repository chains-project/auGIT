
import typer

from augit.cli.context import AppContext, now, parse_dt
from augit.collectors.git_refs import collect_git_refs
from augit.collectors.github_api import GitHubClient, github_repo_key
from augit.collectors.github_integrity_refetch import build_integrity_refetch_view
from augit.integrity_run import execute_integrity_refetch
from augit.models import IntegrityRefetchView


def register_check(app: typer.Typer) -> None:
    @app.command(
        "check",
        help="Integrity check: compare recorded audit trail against a live refetch",
    )
    def check_cmd(
        ctx: typer.Context,
        repo: str = typer.Argument(..., help="owner/repo or GitHub URL"),
        branch: list[str] = typer.Option(
            None, "--branch", help="Branch to refetch (repeatable)"
        ),
        refetched_at: str | None = typer.Option(
            None, "--refetched-at", help="ISO timestamp for refetch"
        ),
        no_git: bool = typer.Option(
            False, "--no-git", help="Skip git ls-remote; use GitHub API only"
        ),
        git_only: bool = typer.Option(
            False,
            "--git-only",
            help="Use git ls-remote only (no GitHub API)",
        ),
        git_remote: str | None = typer.Option(
            None,
            "--git-remote",
            help="Git remote URL (default: https://github.com/owner/repo.git)",
        ),
    ) -> None:
        app_ctx: AppContext = ctx.obj
        store = app_ctx.store
        repo_key = github_repo_key(repo)
        ts = parse_dt(refetched_at) or now()

        if git_only:
            remote_url = git_remote or f"{repo_key.canonical_url}.git"
            ref_events = collect_git_refs(
                repo_key, remote=remote_url, branches=branch or None
            ).events
            branch_reachability: dict[str, list[str]] = {}
            tag_targets: dict[str, str] = {}
            for ev in ref_events:
                payload = ev.payload or {}
                if ev.event_type == "git_branch_tip":
                    b = payload.get("branch")
                    sha = payload.get("sha")
                    if b and sha:
                        branch_reachability[str(b)] = [str(sha)]
                elif ev.event_type == "git_tag_target":
                    t = payload.get("tag")
                    sha = payload.get("sha")
                    if t and sha:
                        tag_targets[str(t)] = str(sha)
            refetched_view = IntegrityRefetchView(
                branch_reachability=branch_reachability,
                tag_targets=tag_targets,
                pull_requests=[],
                releases=[],
                repo_identity={},
            )
        else:
            client = GitHubClient.from_env()
            refetched_view = build_integrity_refetch_view(
                client,
                repo_key,
                remote=git_remote,
                branches=branch or None,
                use_git=not no_git,
            )

        run_result = execute_integrity_refetch(
            store,
            repo_key,
            refetched_view,
            refetched_at=ts,
        )
        typer.echo(
            f"integrity_events={len(run_result.integrity_events)} run_id={run_result.run_id} "
            f"prs={len(refetched_view.pull_requests)} "
            f"releases={len(refetched_view.releases)} tags={len(refetched_view.tag_targets)} "
            f"drift_detected={run_result.summary.get('drift_events_detected', 0)}"
        )
