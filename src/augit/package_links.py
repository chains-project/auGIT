import re
from dataclasses import dataclass
from typing import Any

from augit.collectors.github_api import (
    canonical_github_url,
    github_owner_repo,
    github_repo_key,
)
from augit.collectors.maven import parse_gav
from augit.collectors.pypi import fetch_pypi_json
from augit.deps_dev import fetch_project_package_versions
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
    # Case-insensitive match on preferred field labels.
    field_priority = (
        "project_urls.repository",
        "project_urls.source",
        "project_urls.source code",
        "project_urls.code",
        "project_urls.homepage",
        "home_page",
    )
    by_lower = {field.lower(): (field, url) for field, url in candidates}
    for pref in field_priority:
        if pref in by_lower:
            return by_lower[pref]
    return candidates[0]


def pypi_info_matches_github(info: dict[str, Any], github_key: RepoKey) -> bool:
    """True when PyPI metadata points at *github_key*."""
    want = github_key.canonical_url.rstrip("/").lower()
    for _field, url in github_urls_from_pypi_info(info):
        if url.rstrip("/").lower() == want:
            return True
    return False


@dataclass(frozen=True)
class LinkResult:
    linked: bool
    package_key: RepoKey
    github_key: RepoKey | None
    source_field: str | None
    raw_url: str | None


def link_pypi_package(
    store: EventStore,
    package_name: str,
    *,
    pypi_data: dict[str, Any] | None = None,
) -> LinkResult:
    pkg_key = RepoKey(canonical_url=package_name, provider="pypi")
    data = pypi_data if pypi_data is not None else fetch_pypi_json(package_name)
    if data.get("_augit_missing"):
        return LinkResult(
            linked=False,
            package_key=pkg_key,
            github_key=None,
            source_field=None,
            raw_url=None,
        )
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
    if source_field.lower().startswith("project_urls."):
        key = source_field.split(".", 1)[1]
        project_urls = info.get("project_urls") or {}
        # Case-insensitive key lookup
        raw = next(
            (
                v
                for k, v in project_urls.items()
                if str(k).lower() == key.lower()
            ),
            raw,
        )
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


def link_maven_package(
    store: EventStore,
    gav: str,
    *,
    maven_data: dict[str, Any] | None = None,
) -> LinkResult:
    from augit.collectors.maven import fetch_maven_versions

    g, a = parse_gav(gav)
    pkg_key = RepoKey(canonical_url=f"{g}:{a}", provider="maven")
    data = (
        maven_data
        if maven_data is not None
        else fetch_maven_versions(gav, rows=50)
    )
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


def _pypi_name_guesses(repo_slug: str) -> list[str]:
    """Candidate PyPI names derived from a GitHub owner/repo slug."""
    _owner, repo = repo_slug.split("/", 1)
    names = [
        repo,
        repo.lower(),
        repo.replace("-", "_"),
        repo.replace("_", "-"),
        repo.lower().replace("-", "_"),
        repo.lower().replace("_", "-"),
    ]
    # Preserve order, drop duplicates
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


@dataclass(frozen=True)
class DiscoveredPackage:
    provider: str  # pypi | maven
    name: str  # package name or GAV
    source_field: str
    github_key: RepoKey


def discover_packages_for_github(
    store: EventStore,
    github_key: RepoKey,
    *,
    max_packages: int = 5,
) -> list[DiscoveredPackage]:
    """
    Find PyPI/Maven packages for a GitHub repo and upsert package_links.

    Strategy:
    1. Guess PyPI name from the repo name; accept when metadata points back
       at this GitHub repo, or when the package exists and the name matches
       the repo name (covers packages with empty project_urls).
    2. Query deps.dev for PYPI/MAVEN mappings; keep name-aligned packages
       and those that verify via forward metadata.
    """
    slug = github_owner_repo(github_key)
    repo_name = slug.split("/", 1)[1]
    repo_name_l = repo_name.lower()
    found: list[DiscoveredPackage] = []
    seen: set[tuple[str, str]] = set()

    def add(provider: str, name: str, source_field: str) -> None:
        key = (provider, name.lower() if provider == "pypi" else name)
        if key in seen:
            return
        seen.add(key)
        pkg_key = RepoKey(canonical_url=name, provider=provider)
        store.upsert_package_link(
            pkg_key,
            github_key,
            source_field=source_field,
            raw_url=github_key.canonical_url,
        )
        found.append(
            DiscoveredPackage(
                provider=provider,
                name=name,
                source_field=source_field,
                github_key=github_key,
            )
        )

    # 1) PyPI name heuristics
    for guess in _pypi_name_guesses(slug):
        if len(found) >= max_packages:
            break
        data = fetch_pypi_json(guess)
        if data.get("_augit_missing"):
            continue
        info = data.get("info") or {}
        canonical_name = str(info.get("name") or guess)
        if pypi_info_matches_github(info, github_key):
            add("pypi", canonical_name, "pypi_name_guess+project_urls")
            continue
        # Empty URLs but exact name match (case-insensitive)
        if not github_urls_from_pypi_info(info) and canonical_name.lower() == repo_name_l:
            add("pypi", canonical_name, "pypi_name_guess")

    # 2) deps.dev reverse index
    for pkg in fetch_project_package_versions(github_key):
        if len(found) >= max_packages:
            break
        if pkg.system == "PYPI":
            name_l = pkg.name.lower()
            # Prefer repo-name match; otherwise verify forward link
            data = fetch_pypi_json(pkg.name)
            if data.get("_augit_missing"):
                continue
            info = data.get("info") or {}
            canonical_name = str(info.get("name") or pkg.name)
            if name_l == repo_name_l or pypi_info_matches_github(info, github_key):
                add("pypi", canonical_name, "deps.dev")
        elif pkg.system == "MAVEN":
            # Prefer artifactId == repo name
            try:
                _g, a = parse_gav(pkg.name)
            except ValueError:
                continue
            if a.lower() != repo_name_l and not a.lower().startswith(repo_name_l):
                # Still accept if only a few overall; skip noisy monorepo extras
                # unless exact-ish match
                if repo_name_l not in a.lower() and repo_name_l not in pkg.name.lower():
                    continue
            # Confirm SCM when possible
            from augit.collectors.maven import fetch_maven_versions

            try:
                mdata = fetch_maven_versions(pkg.name, rows=20)
            except Exception:
                mdata = {}
            docs = ((mdata.get("response") or {}).get("docs")) or []
            scm = next((d.get("scm") for d in docs if d.get("scm")), None)
            parsed = github_url_from_maven_scm(scm)
            if parsed is not None and parsed[1] != github_key.canonical_url:
                continue
            if parsed is None and a.lower() != repo_name_l:
                continue
            add("maven", pkg.name, "deps.dev" if parsed is None else "deps.dev+scm")

    return found
