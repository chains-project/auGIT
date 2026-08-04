from augit.collect_target import parse_collect_target
from augit.package_links import pick_primary_github


def test_parse_github_owner_repo():
    t = parse_collect_target("psf/requests")
    assert t.provider == "github"
    assert t.key.canonical_url == "https://github.com/psf/requests"


def test_parse_github_url():
    t = parse_collect_target("https://github.com/psf/requests.git")
    assert t.provider == "github"
    assert t.key.canonical_url == "https://github.com/psf/requests"


def test_parse_pypi_prefix_and_bare():
    assert parse_collect_target("pypi:requests").provider == "pypi"
    assert parse_collect_target("pypi:requests").key.canonical_url == "requests"
    assert parse_collect_target("requests").provider == "pypi"


def test_parse_maven_prefix_and_gav():
    t = parse_collect_target("maven:com.google.guava:guava")
    assert t.provider == "maven"
    assert t.key.canonical_url == "com.google.guava:guava"
    t2 = parse_collect_target("com.google.guava:guava")
    assert t2.provider == "maven"
    assert t2.key.canonical_url == "com.google.guava:guava"


def test_pick_primary_github_case_insensitive():
    candidates = [
        ("project_urls.Docs", "https://github.com/other/docs"),
        ("project_urls.repository", "https://github.com/psf/requests"),
    ]
    picked = pick_primary_github(candidates)
    assert picked is not None
    assert picked[1] == "https://github.com/psf/requests"
