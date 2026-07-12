import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from augit.models import RepoKey


class GitHubApiError(RuntimeError):
    pass


def _parse_rel_link(link_header: str | None, rel: str) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if f'rel="{rel}"' not in part:
            continue
        if part.startswith("<") and ">;" in part:
            return part[1 : part.index(">;")]
    return None


def _parse_next_link(link_header: str | None) -> str | None:
    return _parse_rel_link(link_header, "next")


def _page_from_url(url: str) -> int | None:
    parsed = urllib.parse.urlparse(url)
    pages = urllib.parse.parse_qs(parsed.query).get("page")
    if not pages:
        return None
    try:
        return int(pages[0])
    except ValueError:
        return None


@dataclass(frozen=True)
class GitHubClient:
    token: str | None
    base_url: str = "https://api.github.com"

    @classmethod
    def from_env(cls) -> GitHubClient:
        return cls(token=os.environ.get("GITHUB_TOKEN"))

    def get_json(
        self, path_or_url: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        url = path_or_url
        if url.startswith("/"):
            url = self.base_url.rstrip("/") + url
        if params:
            qs = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            url = url + ("&" if "?" in url else "?") + qs

        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "augit")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw), resp.headers
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise GitHubApiError(f"GitHub API error {e.code} for {url}: {body}") from e

    def graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise GitHubApiError("GraphQL requires GITHUB_TOKEN")

        url = f"{self.base_url.rstrip('/')}/graphql"
        payload = json.dumps(
            {"query": query, "variables": variables or {}},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "augit")
        req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise GitHubApiError(f"GitHub GraphQL error {e.code}: {err_body}") from e

        if body.get("errors"):
            messages = "; ".join(str(err.get("message", err)) for err in body["errors"])
            raise GitHubApiError(f"GitHub GraphQL errors: {messages}")

        self._throttle_graphql(body)
        return body

    def _throttle_graphql(self, body: dict[str, Any]) -> None:
        rate = (body.get("data") or {}).get("rateLimit") or {}
        remaining = rate.get("remaining")
        if remaining is None or remaining >= 100:
            return
        reset_at = rate.get("resetAt")
        if not reset_at:
            time.sleep(2)
            return
        reset_dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        wait = (reset_dt - datetime.now(UTC)).total_seconds()
        if wait > 0:
            time.sleep(min(wait + 1, 120))

    def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Iterable[Any]:
        url: str | None = path
        cur_params = dict(params or {})
        while url is not None:
            data, headers = self.get_json(
                url, params=cur_params if url == path else None
            )
            yield data
            url = _parse_next_link(headers.get("Link"))
            cur_params = {}


GITHUB_CANONICAL_PREFIX = "https://github.com/"


def parse_owner_repo(s: str) -> tuple[str, str]:
    if "/" not in s:
        raise ValueError("repo must be in owner/repo form")
    owner, repo = s.split("/", 1)
    if not owner or not repo:
        raise ValueError("repo must be in owner/repo form")
    return owner, repo


def canonical_github_url(repo: str) -> str:
    """Normalize owner/repo or a GitHub URL to https://github.com/owner/repo."""
    s = repo.strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]

    if s.startswith("git@github.com:"):
        s = s[len("git@github.com:") :]

    lower = s.lower()
    if "github.com/" in lower:
        idx = lower.index("github.com/")
        path = s[idx + len("github.com/") :]
        path = path.split("?", 1)[0].split("#", 1)[0].strip("/")
        owner, name = parse_owner_repo(path)
        return f"{GITHUB_CANONICAL_PREFIX}{owner}/{name}"

    owner, name = parse_owner_repo(s)
    return f"{GITHUB_CANONICAL_PREFIX}{owner}/{name}"


def github_repo_key(repo: str) -> RepoKey:
    return RepoKey(canonical_url=canonical_github_url(repo), provider="github")


def github_owner_repo(repo_key: RepoKey) -> str:
    """Return owner/repo slug derived from a GitHub RepoKey."""
    url = repo_key.canonical_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    lower = url.lower()
    prefix = GITHUB_CANONICAL_PREFIX.lower()
    if not lower.startswith(prefix):
        raise ValueError(f"not a GitHub repo key: {repo_key.canonical_url}")
    slug = url[len(GITHUB_CANONICAL_PREFIX) :]
    parse_owner_repo(slug)
    return slug
