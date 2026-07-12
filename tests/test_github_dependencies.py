import json
from unittest.mock import MagicMock

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_dependencies import (
    _extract_patch_deps,
    _parse_package_json_deps,
    _parse_requirements,
    collect_dependency_changes,
)


def test_parse_package_json_deps_collects_all_sections():
    content = json.dumps(
        {
            "dependencies": {"lodash": "^4.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
            "peerDependencies": {"react": "^18.0.0"},
        }
    )
    deps = _parse_package_json_deps(content)
    assert deps == {"lodash", "jest", "react"}


def test_parse_package_json_deps_handles_invalid_json():
    assert _parse_package_json_deps("{not json") == set()


def test_parse_requirements_skips_comments_and_pins():
    content = """
    # core
    requests>=2.28.0
    urllib3<2
    """
    deps = _parse_requirements(content)
    assert deps == {"requests", "urllib3"}


def test_extract_patch_finds_added_package_json_dependency():
    patch = """@@ -1,5 +1,6 @@
 {
   "dependencies": {
+    "left-pad": "^1.0.0",
     "lodash": "^4.17.21"
   }
 }
"""
    before, after = _extract_patch_deps("package.json", patch)
    assert "left-pad" in after - before
    assert "lodash" in before & after


def test_extract_patch_version_bump_only_produces_no_new_deps():
    patch = """@@ -1,5 +1,5 @@
 {
   "dependencies": {
-    "lodash": "^4.17.20"
+    "lodash": "^4.17.21"
   }
 }
"""
    before, after = _extract_patch_deps("package.json", patch)
    assert before == after == {"lodash"}


def test_extract_patch_finds_added_requirements_dependency():
    patch = """@@ -1,2 +1,3 @@
 requests>=2.28.0
+colorama>=0.4.6
"""
    before, after = _extract_patch_deps("requirements.txt", patch)
    assert "colorama" in after - before
    assert "requests" in before & after


def test_collect_dependency_changes_emits_manifest_event(tmp_path):
    repo_key = github_repo_key("org/repo")
    client = MagicMock()
    client.get_json.side_effect = [
        (
            [
                {
                    "number": 42,
                    "merged_at": "2026-01-15T12:00:00Z",
                    "merge_commit_sha": "abc123",
                    "user": {"login": "alice"},
                }
            ],
            {},
        ),
        (
            [
                {
                    "filename": "package.json",
                    "patch": """@@ -1,4 +1,5 @@
 {
   "dependencies": {
+    "evil-pkg": "^1.0.0",
     "lodash": "^4.0.0"
   }
 }
""",
                }
            ],
            {},
        ),
    ]

    result = collect_dependency_changes(client, repo_key=repo_key, cursor=None)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "dependency_manifest_change"
    assert event.payload["added"] == ["evil-pkg"]
    assert event.payload["pr_number"] == 42
    assert event.payload["author_login"] == "alice"
    assert "pr:42" in result.cursor["processed_prs"]


def test_collect_dependency_changes_skips_non_manifest_files():
    repo_key = github_repo_key("org/repo")
    client = MagicMock()
    client.get_json.side_effect = [
        (
            [
                {
                    "number": 7,
                    "merged_at": "2026-01-15T12:00:00Z",
                    "user": {"login": "bob"},
                }
            ],
            {},
        ),
        (
            [{"filename": "README.md", "patch": "+added line"}],
            {},
        ),
    ]

    result = collect_dependency_changes(client, repo_key=repo_key, cursor=None)

    assert result.events == []


def test_collect_dependency_changes_uses_merged_prs_hint_without_pulls_list():
    repo_key = github_repo_key("org/repo")
    client = MagicMock()
    client.get_json.return_value = (
        [
            {
                "filename": "package.json",
                "patch": """@@ -1,4 +1,5 @@
 {
   "dependencies": {
+    "left-pad": "^1.0.0",
     "lodash": "^4.0.0"
   }
 }
""",
            }
        ],
        {},
    )

    merged_prs = [
        {
            "number": 42,
            "merged_at": "2026-01-15T12:00:00Z",
            "merge_commit_sha": "abc123",
            "user": {"login": "alice"},
        }
    ]
    result = collect_dependency_changes(
        client,
        repo_key=repo_key,
        cursor=None,
        merged_prs=merged_prs,
    )

    assert len(result.events) == 1
    client.get_json.assert_called_once()
    assert client.get_json.call_args[0][0].endswith("/pulls/42/files")
