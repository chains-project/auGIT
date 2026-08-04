import base64
import json
from unittest.mock import MagicMock

from augit.collectors.github_api import github_repo_key
from augit.collectors.github_dependencies import (
    _extract_patch_deps,
    _parse_package_json_deps,
    _parse_pom_deps,
    _parse_pyproject_deps,
    _parse_requirements,
    collect_dependency_changes,
)


def _client_with_no_manifest_commits() -> MagicMock:
    client = MagicMock()
    client.paginate.return_value = iter([])
    return client


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


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
    -r other.txt
    """
    deps = _parse_requirements(content)
    assert deps == {"requests", "urllib3"}


def test_parse_pyproject_project_and_poetry_deps():
    content = """
[project]
dependencies = [
  "requests>=2.28",
  "httpx[http2]",
]
optional-dependencies = {dev = ["pytest>=7"]}

[tool.poetry.dependencies]
python = "^3.11"
colorama = "^0.4"
"""
    deps = _parse_pyproject_deps(content)
    assert deps == {"requests", "httpx", "pytest", "colorama"}


def test_parse_pyproject_invalid_returns_empty():
    assert _parse_pyproject_deps("[[[not toml") == set()


def test_parse_pom_deps_with_namespace():
    content = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>32.0.0</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
    </dependency>
  </dependencies>
</project>
"""
    deps = _parse_pom_deps(content)
    assert deps == {"com.google.guava:guava", "junit:junit"}


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


def test_extract_patch_finds_added_pyproject_dependency():
    patch = """@@ -1,5 +1,6 @@
 [project]
 dependencies = [
+  "evil-pkg>=1.0",
   "requests>=2.28",
 ]
"""
    before, after = _extract_patch_deps("pyproject.toml", patch)
    assert "evil-pkg" in after - before
    assert "requests" in before & after


def test_extract_patch_finds_added_pom_dependency():
    patch = """@@ -1,8 +1,14 @@
 <project>
   <dependencies>
+    <dependency>
+      <groupId>com.evil</groupId>
+      <artifactId>payload</artifactId>
+    </dependency>
     <dependency>
       <groupId>junit</groupId>
       <artifactId>junit</artifactId>
     </dependency>
   </dependencies>
 </project>
"""
    before, after = _extract_patch_deps("pom.xml", patch)
    assert "com.evil:payload" in after - before
    assert "junit:junit" in before & after


def test_extract_patch_incomplete_package_json_hunk_yields_empty():
    """Real GitHub hunks often omit outer braces — patch parse alone is insufficient."""
    patch = """@@ -9,6 +9,7 @@
   },
   "dependencies": {
     "duplexer": "^0.1.1",
+    "flatmap-stream": "^0.1.0",
     "from": "^0.1.7",
     "map-stream": "0.0.7",
"""
    before, after = _extract_patch_deps("package.json", patch)
    assert before == after == set()


def test_collect_dependency_changes_emits_manifest_event():
    repo_key = github_repo_key("org/repo")
    client = _client_with_no_manifest_commits()
    # No merge_commit_sha → patch fallback (complete JSON hunk).
    client.get_json.side_effect = [
        (
            [
                {
                    "number": 42,
                    "merged_at": "2026-01-15T12:00:00Z",
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
    client = _client_with_no_manifest_commits()
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
    client = _client_with_no_manifest_commits()
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


def test_collect_commit_adds_npm_flatmap_stream_via_contents():
    """Incomplete GitHub patch + full file contents at parent/commit."""
    repo_key = github_repo_key("dominictarr/event-stream")
    client = MagicMock()
    sha = "e3163361fed01384c986b9b4c18feb1fc42b8285"
    parent = "0f3738c9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def paginate(_path, *, params=None):
        if (params or {}).get("path") == "package.json":
            return iter([[{"sha": sha}]])
        return iter([[]])

    client.paginate.side_effect = paginate

    before_json = json.dumps(
        {
            "dependencies": {
                "duplexer": "^0.1.1",
                "from": "^0.1.7",
                "map-stream": "0.0.7",
                "through": ">=2.2.7 <3",
            }
        }
    )
    after_json = json.dumps(
        {
            "dependencies": {
                "duplexer": "^0.1.1",
                "flatmap-stream": "^0.1.0",
                "from": "^0.1.7",
                "map-stream": "0.0.7",
                "through": ">=2.2.7 <3",
            }
        }
    )

    def get_json(path_or_url, *, params=None):
        if path_or_url.endswith(f"/commits/{sha}"):
            return (
                {
                    "sha": sha,
                    "author": {"login": "right9ctrl"},
                    "parents": [{"sha": parent}],
                    "commit": {
                        "author": {"date": "2018-09-09T08:07:49Z"},
                        "committer": {"date": "2018-09-09T08:07:49Z"},
                    },
                    "files": [
                        {
                            "filename": "package.json",
                            # Realistic incomplete hunk (not valid JSON alone).
                            "patch": """@@ -9,6 +9,7 @@
   },
   "dependencies": {
     "duplexer": "^0.1.1",
+    "flatmap-stream": "^0.1.0",
     "from": "^0.1.7",
     "map-stream": "0.0.7",
""",
                        }
                    ],
                },
                {},
            )
        if "/contents/package.json" in path_or_url:
            ref = (params or {}).get("ref")
            if ref == parent:
                return (
                    {"encoding": "base64", "content": _b64(before_json)},
                    {},
                )
            if ref == sha:
                return (
                    {"encoding": "base64", "content": _b64(after_json)},
                    {},
                )
        raise AssertionError(f"unexpected get_json {path_or_url} {params}")

    client.get_json.side_effect = get_json

    result = collect_dependency_changes(
        client, repo_key=repo_key, cursor=None, merged_prs=[]
    )

    assert len(result.events) == 1
    event = result.events[0]
    assert event.payload["added"] == ["flatmap-stream"]
    assert event.payload["pr_number"] is None
    assert event.payload["author_login"] == "right9ctrl"
    assert event.payload["commit_sha"].startswith("e316336")
    assert sha in result.cursor["processed_commits"]


def test_collect_commit_skips_already_processed_sha():
    repo_key = github_repo_key("org/repo")
    client = MagicMock()
    client.paginate.side_effect = lambda *_a, **_k: iter([[{"sha": "aaa111"}]])
    result = collect_dependency_changes(
        client,
        repo_key=repo_key,
        cursor={"processed_prs": [], "processed_commits": ["aaa111"]},
        merged_prs=[],
    )
    assert result.events == []
    client.get_json.assert_not_called()


def test_collect_commit_adds_requirements_and_pom_via_contents():
    repo_key = github_repo_key("org/repo")
    client = MagicMock()

    def paginate(_path, *, params=None):
        manifest = (params or {}).get("path")
        if manifest == "requirements.txt":
            return iter([[{"sha": "reqsha1"}]])
        if manifest == "pom.xml":
            return iter([[{"sha": "pomsha1"}]])
        return iter([[]])

    client.paginate.side_effect = paginate

    req_parent = "reqparent"
    pom_parent = "pomparent"
    before_req = "requests>=2.28\n"
    after_req = "requests>=2.28\nevil-lib==1.0\n"
    before_pom = """<project><dependencies>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId></dependency>
  </dependencies></project>"""
    after_pom = """<project><dependencies>
    <dependency><groupId>com.evil</groupId><artifactId>payload</artifactId></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId></dependency>
  </dependencies></project>"""

    def get_json(path_or_url, *, params=None):
        if path_or_url.endswith("/commits/reqsha1"):
            return (
                {
                    "sha": "reqsha1",
                    "author": {"login": "pip-user"},
                    "parents": [{"sha": req_parent}],
                    "commit": {"committer": {"date": "2024-01-01T00:00:00Z"}},
                    "files": [{"filename": "requirements.txt"}],
                },
                {},
            )
        if path_or_url.endswith("/commits/pomsha1"):
            return (
                {
                    "sha": "pomsha1",
                    "author": {"login": "mvn-user"},
                    "parents": [{"sha": pom_parent}],
                    "commit": {"committer": {"date": "2024-01-02T00:00:00Z"}},
                    "files": [{"filename": "pom.xml"}],
                },
                {},
            )
        if "/contents/requirements.txt" in path_or_url:
            ref = (params or {}).get("ref")
            text = after_req if ref == "reqsha1" else before_req
            return ({"encoding": "base64", "content": _b64(text)}, {})
        if "/contents/pom.xml" in path_or_url:
            ref = (params or {}).get("ref")
            text = after_pom if ref == "pomsha1" else before_pom
            return ({"encoding": "base64", "content": _b64(text)}, {})
        raise AssertionError(f"unexpected get_json {path_or_url} {params}")

    client.get_json.side_effect = get_json

    result = collect_dependency_changes(
        client, repo_key=repo_key, cursor=None, merged_prs=[]
    )
    added = {tuple(e.payload["added"]) for e in result.events}
    assert ("evil-lib",) in added
    assert ("com.evil:payload",) in added
