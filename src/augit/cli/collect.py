from sqlite3 import OperationalError

import typer

from augit.cli.collect_github import collect_github_sources, parse_sources
from augit.cli.context import AppContext
from augit.collect_linked import collect_linked
from augit.collectors.github_api import GitHubClient, github_repo_key
from augit.collectors.maven import collect_maven_versions
from augit.collectors.npm import collect_npm_versions
from augit.collectors.pypi import collect_pypi_versions
from augit.models import RepoKey
from augit.package_links import link_maven_package, link_npm_package, link_pypi_package

collect_app = typer.Typer(help="Collect audit events from external sources")


def _echo_linked_result(result) -> None:
    for side in result.sides:
        bits = [f"{side.provider} {side.display}", f"inserted={side.inserted}"]
        if side.linked_to:
            bits.append(f"linked={side.linked_to}")
        if side.note:
            bits.append(f"({side.note})")
        typer.echo(" ".join(bits))


@collect_app.command("auto")
def collect_auto(
    ctx: typer.Context,
    target: str = typer.Argument(
        ...,
        help=(
            "GitHub owner/repo or URL, PyPI name, pypi:name, npm:name, "
            "maven groupId:artifactId, or maven:g:a"
        ),
    ),
    sources: str = typer.Option(
        "all",
        "--sources",
        help="GitHub sources: all or comma-separated prs,commits,releases,tags,dependencies,git_refs",
    ),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Also resolve and collect the linked GitHub or registry side",
    ),
    max_packages: int = typer.Option(
        5,
        "--max-packages",
        help="Max registry packages to collect when starting from GitHub",
    ),
) -> None:
    """Collect a target and automatically collect the linked other side."""
    app_ctx: AppContext = ctx.obj
    try:
        source_list = parse_sources(sources)
        result = collect_linked(
            app_ctx.store,
            target,
            sources=source_list,
            follow=follow,
            max_packages=max_packages,
        )
        _echo_linked_result(result)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except OperationalError as exc:
        raise typer.BadParameter(
            "Database could not be accessed (possibly locked). "
            "Pass --db PATH or set SSC_AUDIT_DB."
        ) from exc


@collect_app.command("github")
def collect_github(
    ctx: typer.Context,
    repo: str = typer.Argument(..., help="owner/repo or GitHub URL"),
    sources: str = typer.Option(
        "all",
        "--sources",
        help="all or comma-separated: prs,commits,releases,tags,dependencies,git_refs",
    ),
    follow: bool = typer.Option(
        False,
        "--follow/--no-follow",
        help="Also discover and collect linked PyPI, Maven, and npm packages",
    ),
) -> None:
    app_ctx: AppContext = ctx.obj
    try:
        source_list = parse_sources(sources)
        if follow:
            result = collect_linked(
                app_ctx.store,
                repo,
                sources=source_list,
                follow=True,
            )
            if result.target.provider != "github":
                raise typer.BadParameter(
                    f"expected a GitHub target, got {result.target.provider}: {repo}"
                )
            _echo_linked_result(result)
            return

        store = app_ctx.store
        client = GitHubClient.from_env()
        repo_key = github_repo_key(repo)
        result = collect_github_sources(store, client, repo_key, source_list)

        total = sum(result.inserted_by_source.values())
        parts = " ".join(f"{k}={v}" for k, v in result.inserted_by_source.items())
        typer.echo(
            f"inserted={total} sources={','.join(source_list)} "
            f"run_ids={result.run_ids} {parts}"
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except OperationalError as exc:
        raise typer.BadParameter(
            "Database could not be accessed (possibly locked). "
            "Pass --db PATH or set SSC_AUDIT_DB."
        ) from exc


@collect_app.command("pypi")
def collect_pypi(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="PyPI package name"),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Also collect the linked GitHub repository when metadata provides one",
    ),
    sources: str = typer.Option(
        "all",
        "--sources",
        help="GitHub sources used when --follow collects the linked repo",
    ),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store

    if follow:
        result = collect_linked(
            store,
            f"pypi:{name}",
            sources=parse_sources(sources),
            follow=True,
        )
        _echo_linked_result(result)
        return

    pkg_key = RepoKey(canonical_url=name, provider="pypi")
    pkg_id = store.ensure_repo(pkg_key)
    run_id = store.start_run(pkg_id, mode="incremental")

    cursor = store.get_cursor(pkg_key, "pypi_versions")
    result = collect_pypi_versions(package_name=name, cursor=cursor)
    inserted = store.append_events(run_id, result.events)
    store.set_cursor(pkg_key, "pypi_versions", result.cursor)
    store.finish_run(run_id)

    link = link_pypi_package(store, name)
    if link.linked:
        typer.echo(
            f"linked pypi:{name} -> {link.github_key.canonical_url} ({link.source_field})"
        )
    else:
        typer.echo(f"no github link found for pypi:{name}")

    typer.echo(f"inserted={inserted} run_id={run_id}")


@collect_app.command("maven")
def collect_maven(
    ctx: typer.Context,
    gav: str = typer.Argument(..., help="Maven coordinates groupId:artifactId"),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Also collect the linked GitHub repository when SCM provides one",
    ),
    sources: str = typer.Option(
        "all",
        "--sources",
        help="GitHub sources used when --follow collects the linked repo",
    ),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store

    if follow:
        result = collect_linked(
            store,
            f"maven:{gav}",
            sources=parse_sources(sources),
            follow=True,
        )
        _echo_linked_result(result)
        return

    pkg_key = RepoKey(canonical_url=gav, provider="maven")
    pkg_id = store.ensure_repo(pkg_key)
    run_id = store.start_run(pkg_id, mode="incremental")

    cursor = store.get_cursor(pkg_key, "maven_versions")
    result = collect_maven_versions(gav=gav, cursor=cursor)
    inserted = store.append_events(run_id, result.events)
    store.set_cursor(pkg_key, "maven_versions", result.cursor)
    store.finish_run(run_id)

    link = link_maven_package(store, gav)
    if link.linked:
        typer.echo(
            f"linked maven:{gav} -> {link.github_key.canonical_url} ({link.source_field})"
        )
    else:
        typer.echo(f"no github link found for maven:{gav}")

    typer.echo(f"inserted={inserted} run_id={run_id}")


@collect_app.command("npm")
def collect_npm(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="npm package name"),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Also collect the linked GitHub repository when metadata provides one",
    ),
    sources: str = typer.Option(
        "all",
        "--sources",
        help="GitHub sources used when --follow collects the linked repo",
    ),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store

    if follow:
        result = collect_linked(
            store,
            f"npm:{name}",
            sources=parse_sources(sources),
            follow=True,
        )
        _echo_linked_result(result)
        return

    pkg_key = RepoKey(canonical_url=name, provider="npm")
    pkg_id = store.ensure_repo(pkg_key)
    run_id = store.start_run(pkg_id, mode="incremental")

    cursor = store.get_cursor(pkg_key, "npm_versions")
    result = collect_npm_versions(package_name=name, cursor=cursor)
    inserted = store.append_events(run_id, result.events)
    store.set_cursor(pkg_key, "npm_versions", result.cursor)
    store.finish_run(run_id)

    link = link_npm_package(store, name)
    if link.linked:
        typer.echo(
            f"linked npm:{name} -> {link.github_key.canonical_url} ({link.source_field})"
        )
    else:
        typer.echo(f"no github link found for npm:{name}")

    typer.echo(f"inserted={inserted} run_id={run_id}")
