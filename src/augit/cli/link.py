import json

import typer

from augit.cli.context import AppContext
from augit.models import RepoKey
from augit.package_links import link_maven_package, link_pypi_package

link_app = typer.Typer(help="Link PyPI/Maven packages to GitHub repositories")


@link_app.command("pypi")
def link_pypi(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="PyPI package name"),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store
    link = link_pypi_package(store, name)
    if link.linked:
        typer.echo(
            f"linked pypi:{name} -> {link.github_key.canonical_url} ({link.source_field})"
        )
    else:
        typer.echo(f"no github link found for pypi:{name}")
        raise typer.Exit(code=1)


@link_app.command("maven")
def link_maven(
    ctx: typer.Context,
    gav: str = typer.Argument(..., help="Maven coordinates groupId:artifactId"),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store
    link = link_maven_package(store, gav)
    if link.linked:
        typer.echo(
            f"linked maven:{gav} -> {link.github_key.canonical_url} ({link.source_field})"
        )
    else:
        typer.echo(f"no github link found for maven:{gav}")
        raise typer.Exit(code=1)


@link_app.command("show")
def link_show(
    ctx: typer.Context,
    package: str = typer.Argument(..., help="PyPI name or maven groupId:artifactId"),
    provider: str = typer.Option(..., "--provider", help="pypi or maven"),
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store
    pkg_key = RepoKey(canonical_url=package, provider=provider)
    link = store.get_package_link(pkg_key)
    if link is None:
        typer.echo(f"no link for {provider}:{package}")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(link, default=str))
