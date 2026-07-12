import json
from pathlib import Path
from unittest.mock import patch
import urllib.error
import urllib.request

from augit.collectors.pypi import collect_pypi_versions


def test_collect_pypi_versions_emits_name_version_events():
    fixture = Path(__file__).parent / "fixtures" / "pypi_requests_min.json"
    data = json.loads(fixture.read_text("utf-8"))

    result = collect_pypi_versions(package_name="requests", cursor=None, pypi_json=data)
    assert len(result.events) == 2
    assert result.events[0].source_event_id.startswith("pypi:requests:")
    assert result.cursor["versions"] == ["1.0.0", "2.0.0"]


def test_collect_pypi_versions_emits_missing_event_on_404():
    def raise_404(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://pypi.org/pypi/ctx/json",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    with patch.object(urllib.request, "urlopen", side_effect=raise_404):
        result = collect_pypi_versions(package_name="ctx", cursor=None)
    assert any(e.event_type == "pypi_project_missing" for e in result.events)
