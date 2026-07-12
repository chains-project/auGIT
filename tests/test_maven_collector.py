import json
from pathlib import Path

from augit.collectors.maven import collect_maven_versions


def test_collect_maven_versions_emits_gav_version_events():
    fixture = Path(__file__).parent / "fixtures" / "maven_gav_min.json"
    data = json.loads(fixture.read_text("utf-8"))

    result = collect_maven_versions(
        gav="com.example:demo", cursor=None, maven_json=data
    )
    assert len(result.events) == 2
    assert result.events[0].source_event_id.startswith("maven:com.example:demo:")
    assert result.cursor["versions"] == ["1.0.0", "2.0.0"]
