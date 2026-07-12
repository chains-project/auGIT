import json
from pathlib import Path

from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import RepoKey
from augit.package_links import (
    github_url_from_maven_scm,
    github_urls_from_pypi_info,
    link_maven_package,
    link_pypi_package,
    pick_primary_github,
)
from augit.store import EventStore


def test_pypi_github_urls_from_info():
    info = {
        "home_page": "https://github.com/psf/requests",
        "project_urls": {
            "Documentation": "https://requests.readthedocs.io",
            "Repository": "https://github.com/psf/requests",
        },
        "package_url": "https://pypi.org/project/requests/",
    }
    candidates = github_urls_from_pypi_info(info)
    picked = pick_primary_github(candidates)
    assert picked is not None
    field, url = picked
    assert field == "project_urls.Repository"
    assert url == "https://github.com/psf/requests"


def test_maven_scm_parses_git_ssh():
    parsed = github_url_from_maven_scm("scm:git:git@github.com:apache/commons-lang.git")
    assert parsed is not None
    assert parsed[1] == "https://github.com/apache/commons-lang"


def test_upsert_package_link_roundtrip(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    # Inject GitHub homepage for linking test
    data["info"]["home_page"] = "https://github.com/psf/requests"
    data["info"]["project_urls"] = {"Repository": "https://github.com/psf/requests"}

    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda _name: data,
    )

    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    result = link_pypi_package(store, "requests")
    assert result.linked is True
    assert result.github_key == github_repo_key("psf/requests")

    pkg_key = RepoKey(canonical_url="requests", provider="pypi")
    gh = store.get_github_for_package(pkg_key)
    assert gh is not None
    assert gh.canonical_url == "https://github.com/psf/requests"


def test_link_maven_from_fixture(monkeypatch, tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "maven_gav_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    data["response"]["docs"][0]["scm"] = "scm:git:https://github.com/example/demo.git"

    monkeypatch.setattr(
        "augit.collectors.maven.fetch_maven_versions",
        lambda _gav, rows=200: data,
    )

    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    result = link_maven_package(store, "com.example:demo")
    assert result.linked is True
    assert result.github_key.canonical_url == "https://github.com/example/demo"
