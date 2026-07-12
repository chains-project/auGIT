from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["contributor", "governance", "release", "dependency", "integrity"]
Source = Literal["github_api", "git", "registry", "refetch_compare", "manual"]
RunMode = Literal["incremental", "integrity_refetch"]


class RepoKey(BaseModel):
    canonical_url: str
    provider: str = "github"


class EventIn(BaseModel):
    repo: RepoKey
    category: Category
    event_type: str
    source: Source
    source_event_id: str | None = None
    source_timestamp: datetime | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    payload: dict[str, Any] = Field(default_factory=dict)


class IntegrityRefetchView(BaseModel):
    branch_reachability: dict[str, list[str]] = Field(default_factory=dict)
    tag_targets: dict[str, str] = Field(default_factory=dict)
    pull_requests: list[dict[str, Any]] = Field(default_factory=list)
    releases: list[dict[str, Any]] = Field(default_factory=list)
    repo_identity: dict[str, Any] = Field(default_factory=dict)


class IntegrityEventPayload(BaseModel):
    subtype: Literal[
        "commit_missing",
        "commit_added",
        "tag_retargeted",
        "tag_missing",
        "tag_added",
        "pr_missing",
        "pr_added",
        "release_missing",
        "release_added",
        "repo_moved",
    ]
    severity: Literal["low", "high"]
    expected: Any | None = None
    observed: Any | None = None
    prior_observed_at: datetime | None = None
    refetched_at: datetime
