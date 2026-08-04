import json
from pathlib import Path

from augit.collectors.github_api import github_repo_key
from augit.db import DbConfig, connect
from augit.migrate import migrate
from augit.models import RepoKey
from augit.package_links import discover_packages_for_github
from augit.store import EventStore


def test_discover_packages_pypi_name_guess_with_urls(tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))
    data["info"]["name"] = "requests"
    data["info"]["home_page"] = "https://github.com/psf/requests"
    data["info"]["project_urls"] = {"Source": "https://github.com/psf/requests"}

    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda name: data if name.lower() == "requests" else {"_augit_missing": True},
    )
    monkeypatch.setattr(
        "augit.package_links.fetch_project_package_versions",
        lambda _key: [],
    )

    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    gh = github_repo_key("psf/requests")
    found = discover_packages_for_github(store, gh)
    assert len(found) == 1
    assert found[0].provider == "pypi"
    assert found[0].name == "requests"
    pkgs = store.get_packages_for_github(gh)
    assert pkgs == [RepoKey(canonical_url="requests", provider="pypi")]


def test_discover_packages_name_match_without_urls(tmp_path, monkeypatch):
    data = {
        "info": {"name": "mrmustard", "home_page": None, "project_urls": None},
        "releases": {},
    }
    monkeypatch.setattr(
        "augit.package_links.fetch_pypi_json",
        lambda name: data if name.lower() == "mrmustard" else {"_augit_missing": True},
    )
    monkeypatch.setattr(
        "augit.package_links.fetch_project_package_versions",
        lambda _key: [],
    )

    db_path = tmp_path / "audit.db"
    conn = connect(DbConfig(path=db_path))
    migrate(conn)
    store = EventStore(conn)

    gh = github_repo_key("XanaduAI/MrMustard")
    found = discover_packages_for_github(store, gh)
    assert len(found) == 1
    assert found[0].name == "mrmustard"
