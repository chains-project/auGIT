"""Collect GitHub and/or registry sides, resolving links automatically."""

from __future__ import annotations

from dataclasses import dataclass, field

from augit.cli.collect_github import collect_github_sources
from augit.collect_target import CollectTarget, parse_collect_target
from augit.collectors.github_api import GitHubClient
from augit.collectors.maven import collect_maven_versions
from augit.collectors.pypi import collect_pypi_versions
from augit.models import RepoKey
from augit.package_links import discover_packages_for_github, link_maven_package, link_pypi_package
from augit.store import EventStore


@dataclass
class CollectSideResult:
    provider: str
    display: str
    inserted: int
    linked_to: str | None = None
    note: str | None = None


@dataclass
class LinkedCollectResult:
    target: CollectTarget
    sides: list[CollectSideResult] = field(default_factory=list)


def _collect_pypi_only(store: EventStore, name: str) -> tuple[int, object]:
    pkg_key = RepoKey(canonical_url=name, provider="pypi")
    pkg_id = store.ensure_repo(pkg_key)
    run_id = store.start_run(pkg_id, mode="incremental")
    cursor = store.get_cursor(pkg_key, "pypi_versions")
    result = collect_pypi_versions(package_name=name, cursor=cursor)
    inserted = store.append_events(run_id, result.events)
    store.set_cursor(pkg_key, "pypi_versions", result.cursor)
    store.finish_run(run_id)
    link = link_pypi_package(store, name)
    return inserted, link


def _collect_maven_only(store: EventStore, gav: str) -> tuple[int, object]:
    pkg_key = RepoKey(canonical_url=gav, provider="maven")
    pkg_id = store.ensure_repo(pkg_key)
    run_id = store.start_run(pkg_id, mode="incremental")
    cursor = store.get_cursor(pkg_key, "maven_versions")
    result = collect_maven_versions(gav=gav, cursor=cursor)
    inserted = store.append_events(run_id, result.events)
    store.set_cursor(pkg_key, "maven_versions", result.cursor)
    store.finish_run(run_id)
    link = link_maven_package(store, gav)
    return inserted, link


def _collect_github_only(
    store: EventStore,
    client: GitHubClient,
    repo_key: RepoKey,
    sources: list[str],
) -> int:
    result = collect_github_sources(store, client, repo_key, sources)  # type: ignore[arg-type]
    return sum(result.inserted_by_source.values())


def collect_linked(
    store: EventStore,
    raw_target: str,
    *,
    sources: list[str] | None = None,
    follow: bool = True,
    max_packages: int = 5,
    github_client: GitHubClient | None = None,
) -> LinkedCollectResult:
    """
    Collect a GitHub repo or registry package and, when *follow* is true,
    resolve and collect the linked other side.
    """
    from augit.cli.collect_github import parse_sources

    target = parse_collect_target(raw_target)
    source_list = parse_sources(",".join(sources) if sources else "all")
    out = LinkedCollectResult(target=target)

    if target.provider == "pypi":
        inserted, link = _collect_pypi_only(store, target.key.canonical_url)
        linked_to = link.github_key.canonical_url if link.linked and link.github_key else None
        out.sides.append(
            CollectSideResult(
                provider="pypi",
                display=target.display,
                inserted=inserted,
                linked_to=linked_to,
                note=None if link.linked else "no github link in PyPI metadata",
            )
        )
        if follow and link.linked and link.github_key is not None:
            client = github_client or GitHubClient.from_env()
            gh_inserted = _collect_github_only(store, client, link.github_key, source_list)
            out.sides.append(
                CollectSideResult(
                    provider="github",
                    display=link.github_key.canonical_url,
                    inserted=gh_inserted,
                    linked_to=target.display,
                )
            )
        return out

    if target.provider == "maven":
        inserted, link = _collect_maven_only(store, target.key.canonical_url)
        linked_to = link.github_key.canonical_url if link.linked and link.github_key else None
        out.sides.append(
            CollectSideResult(
                provider="maven",
                display=target.display,
                inserted=inserted,
                linked_to=linked_to,
                note=None if link.linked else "no github link in Maven SCM metadata",
            )
        )
        if follow and link.linked and link.github_key is not None:
            client = github_client or GitHubClient.from_env()
            gh_inserted = _collect_github_only(store, client, link.github_key, source_list)
            out.sides.append(
                CollectSideResult(
                    provider="github",
                    display=link.github_key.canonical_url,
                    inserted=gh_inserted,
                    linked_to=target.display,
                )
            )
        return out

    # GitHub
    client = github_client or GitHubClient.from_env()
    gh_inserted = _collect_github_only(store, client, target.key, source_list)
    out.sides.append(
        CollectSideResult(
            provider="github",
            display=target.display,
            inserted=gh_inserted,
        )
    )
    if not follow:
        return out

    discovered = discover_packages_for_github(store, target.key, max_packages=max_packages)
    if not discovered:
        out.sides[-1].note = "no linked PyPI/Maven package found"
        return out

    for pkg in discovered:
        if pkg.provider == "pypi":
            inserted, _link = _collect_pypi_only(store, pkg.name)
            out.sides.append(
                CollectSideResult(
                    provider="pypi",
                    display=f"pypi:{pkg.name}",
                    inserted=inserted,
                    linked_to=target.display,
                    note=f"via {pkg.source_field}",
                )
            )
        elif pkg.provider == "maven":
            inserted, _link = _collect_maven_only(store, pkg.name)
            out.sides.append(
                CollectSideResult(
                    provider="maven",
                    display=f"maven:{pkg.name}",
                    inserted=inserted,
                    linked_to=target.display,
                    note=f"via {pkg.source_field}",
                )
            )
    return out
