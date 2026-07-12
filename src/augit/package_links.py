import re
from dataclasses import dataclass
from typing import Any

from augit.collectors.github_api import canonical_github_url
from augit.collectors.maven import parse_gav
from augit.collectors.pypi import fetch_pypi_json
from augit.models import RepoKey
from augit.store import EventStore

_GITHUB_HOST = re.compile(r"github\.com", re.I)


def try_canonical_github_url(url: str | None) -> str | None:
    """Return canonical GitHub URL if *url* points at github.com, else None."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u or not _GITHUB_HOST.search(u):
        return None
    try:
        return canonical_github_url(u)
    except ValueError:
        return None


def github_url_from_maven_scm(scm: str | None) -> tuple[str, str] | None:
    """
    Parse Maven SCM string to (source_field, canonical_github_url).
    Examples: scm:git:git@github.com:org/repo.git, scm:git:https://github.com/org/repo
    """
    if not scm or not isinstance(scm, str):
        return None
    s = scm.strip()
    for prefix in ("scm:git:", "scm:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    canonical = try_canonical_github_url(s)
    if canonical is None and s.startswith("git@github.com:"):
        canonical = try_canonical_github_url(s)
    if canonical is None:
        return None
    return ("scm", canonical)


def github_urls_from_pypi_info(info: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Collect candidate GitHub URLs from PyPI project metadata.
    Returns list of (source_field, canonical_github_url).
    """
    out: list[tuple[str, str]] = []

    def add(field: str, raw: str | None) -> None:
        canonical = try_canonical_github_url(raw)
        if canonical:
            out.append((field, canonical))

    add("home_page", info.get("home_page"))

    project_urls = info.get("project_urls") or {}
    if isinstance(project_urls, dict):
        for key, val in project_urls.items():
            add(f"project_urls.{key}", val)

    add("package_url", info.get("package_url"))

    return out


def pick_primary_github(candidates: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Prefer Repository / Source / homepage-style fields over generic keys."""
    if not candidates:
        return None
    field_priority = (
        "project_urls.Repository",
        "project_urls.Source",
        "project_urls.Homepage",
        "home_page",
    )
    for pref in field_priority:
        for field, url in candidates:
            if field == pref:
                return (field, url)
    return candidates[0]


@dataclass(frozen=True)
class LinkResult:
    linked: bool
    package_key: RepoKey
    github_key: RepoKey | None
    source_field: str | None
    raw_url: str | None


def link_pypi_package(store: EventStore, package_name: str) -> LinkResult:
    pkg_key = RepoKey(canonical_url=package_name, provider="pypi")
    data = fetch_pypi_json(package_name)
    info = data.get("info") or {}
    candidates = github_urls_from_pypi_info(info)
    picked = pick_primary_github(candidates)
    if picked is None:
        return LinkResult(
            linked=False,
            package_key=pkg_key,
            github_key=None,
            source_field=None,
            raw_url=None,
        )

    source_field, canonical = picked
    raw = info.get("home_page")
    if source_field.startswith("project_urls."):
        key = source_field.split(".", 1)[1]
        raw = (info.get("project_urls") or {}).get(key) or raw
    github_key = RepoKey(canonical_url=canonical, provider="github")
    store.upsert_package_link(
        pkg_key, github_key, source_field=source_field, raw_url=raw or canonical
    )
    return LinkResult(
        linked=True,
        package_key=pkg_key,
        github_key=github_key,
        source_field=source_field,
        raw_url=raw or canonical,
    )


def link_maven_package(store: EventStore, gav: str) -> LinkResult:
    from augit.collectors.maven import fetch_maven_versions

    g, a = parse_gav(gav)
    pkg_key = RepoKey(canonical_url=f"{g}:{a}", provider="maven")
    data = fetch_maven_versions(gav, rows=50)
    docs = ((data.get("response") or {}).get("docs")) or []

    scm: str | None = None
    for d in docs:
        if d.get("scm"):
            scm = d.get("scm")
            break

    parsed = github_url_from_maven_scm(scm)
    if parsed is None:
        return LinkResult(
            linked=False,
            package_key=pkg_key,
            github_key=None,
            source_field=None,
            raw_url=None,
        )

    source_field, canonical = parsed
    github_key = RepoKey(canonical_url=canonical, provider="github")
    store.upsert_package_link(
        pkg_key, github_key, source_field=source_field, raw_url=scm or canonical
    )
    return LinkResult(
        linked=True,
        package_key=pkg_key,
        github_key=github_key,
        source_field=source_field,
        raw_url=scm or canonical,
    )
