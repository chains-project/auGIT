from collections.abc import Iterable
from datetime import datetime
from typing import Any

from augit.integrity_identity import normalize_repo_identity
from augit.models import EventIn, IntegrityEventPayload, IntegrityRefetchView, RepoKey
from augit.util import utc_now


def _append_drift_event(
    events: list[EventIn],
    *,
    repo: RepoKey,
    payload: IntegrityEventPayload,
    source_event_id: str,
    refetched_at: datetime,
) -> None:
    events.append(
        EventIn(
            repo=repo,
            category="integrity",
            event_type="integrity_drift",
            source="refetch_compare",
            source_event_id=source_event_id,
            source_timestamp=refetched_at,
            observed_at=refetched_at,
            payload=payload.model_dump(mode="json"),
        )
    )


def compare_refetch_views(
    repo: RepoKey,
    recorded_view: IntegrityRefetchView | None,
    refetched_view: IntegrityRefetchView,
    *,
    prior_observed_at: datetime | None,
    refetched_at: datetime | None = None,
    high_severity_branches: set[str] | None = None,
) -> list[EventIn]:
    """Compare recorded audit-trail subjects against a live refetch."""
    refetched_at = refetched_at or utc_now()
    high_severity_branches = high_severity_branches or {"main", "master"}

    events: list[EventIn] = []

    if recorded_view is not None:
        for branch, prior_commits in recorded_view.branch_reachability.items():
            new_commits = set(refetched_view.branch_reachability.get(branch, []))
            severity = "high" if branch in high_severity_branches else "low"
            prior_set = set(prior_commits)
            missing = sorted(prior_set - new_commits)
            added = sorted(new_commits - prior_set)

            for sha in missing:
                payload = IntegrityEventPayload(
                    subtype="commit_missing",
                    severity=severity,
                    expected={"branch": branch, "sha": sha},
                    observed=None,
                    prior_observed_at=prior_observed_at,
                    refetched_at=refetched_at,
                )
                _append_drift_event(
                    events,
                    repo=repo,
                    payload=payload,
                    source_event_id=f"commit_missing:{branch}:{sha}",
                    refetched_at=refetched_at,
                )

            for sha in added:
                payload = IntegrityEventPayload(
                    subtype="commit_added",
                    severity=severity,
                    expected=None,
                    observed={"branch": branch, "sha": sha},
                    prior_observed_at=prior_observed_at,
                    refetched_at=refetched_at,
                )
                _append_drift_event(
                    events,
                    repo=repo,
                    payload=payload,
                    source_event_id=f"commit_added:{branch}:{sha}",
                    refetched_at=refetched_at,
                )

    prior_tags = recorded_view.tag_targets if recorded_view is not None else {}
    new_tags = refetched_view.tag_targets
    for tag, prior_sha in prior_tags.items():
        if tag not in new_tags:
            payload = IntegrityEventPayload(
                subtype="tag_missing",
                severity="high",
                expected={"tag": tag, "sha": prior_sha},
                observed=None,
                prior_observed_at=prior_observed_at,
                refetched_at=refetched_at,
            )
            _append_drift_event(
                events,
                repo=repo,
                payload=payload,
                source_event_id=f"tag_missing:{tag}:{prior_sha}",
                refetched_at=refetched_at,
            )
            continue

        new_sha = new_tags[tag]
        if new_sha != prior_sha:
            payload = IntegrityEventPayload(
                subtype="tag_retargeted",
                severity="high",
                expected={"tag": tag, "sha": prior_sha},
                observed={"tag": tag, "sha": new_sha},
                prior_observed_at=prior_observed_at,
                refetched_at=refetched_at,
            )
            _append_drift_event(
                events,
                repo=repo,
                payload=payload,
                source_event_id=f"tag_retargeted:{tag}:{prior_sha}->{new_sha}",
                refetched_at=refetched_at,
            )

    for tag, new_sha in new_tags.items():
        if tag not in prior_tags:
            payload = IntegrityEventPayload(
                subtype="tag_added",
                severity="low",
                expected=None,
                observed={"tag": tag, "sha": new_sha},
                prior_observed_at=prior_observed_at,
                refetched_at=refetched_at,
            )
            _append_drift_event(
                events,
                repo=repo,
                payload=payload,
                source_event_id=f"tag_added:{tag}:{new_sha}",
                refetched_at=refetched_at,
            )

    def _idset(items: Iterable[dict[str, Any]], key: str) -> set[str]:
        out: set[str] = set()
        for it in items:
            if key in it and it[key] is not None:
                out.add(str(it[key]))
        return out

    prior_pr_ids = _idset(
        recorded_view.pull_requests if recorded_view else [], "pr_number"
    )
    new_pr_ids = _idset(refetched_view.pull_requests, "pr_number")
    for pr in sorted(prior_pr_ids - new_pr_ids):
        payload = IntegrityEventPayload(
            subtype="pr_missing",
            severity="low",
            expected={"pr_number": pr},
            observed=None,
            prior_observed_at=prior_observed_at,
            refetched_at=refetched_at,
        )
        _append_drift_event(
            events,
            repo=repo,
            payload=payload,
            source_event_id=f"pr_missing:{pr}",
            refetched_at=refetched_at,
        )

    for pr in sorted(new_pr_ids - prior_pr_ids):
        payload = IntegrityEventPayload(
            subtype="pr_added",
            severity="low",
            expected=None,
            observed={"pr_number": pr},
            prior_observed_at=prior_observed_at,
            refetched_at=refetched_at,
        )
        _append_drift_event(
            events,
            repo=repo,
            payload=payload,
            source_event_id=f"pr_added:{pr}",
            refetched_at=refetched_at,
        )

    prior_rel_ids = _idset(
        recorded_view.releases if recorded_view else [], "release_id"
    )
    new_rel_ids = _idset(refetched_view.releases, "release_id")
    for rid in sorted(prior_rel_ids - new_rel_ids):
        payload = IntegrityEventPayload(
            subtype="release_missing",
            severity="high",
            expected={"release_id": rid},
            observed=None,
            prior_observed_at=prior_observed_at,
            refetched_at=refetched_at,
        )
        _append_drift_event(
            events,
            repo=repo,
            payload=payload,
            source_event_id=f"release_missing:{rid}",
            refetched_at=refetched_at,
        )

    for rid in sorted(new_rel_ids - prior_rel_ids):
        payload = IntegrityEventPayload(
            subtype="release_added",
            severity="low",
            expected=None,
            observed={"release_id": rid},
            prior_observed_at=prior_observed_at,
            refetched_at=refetched_at,
        )
        _append_drift_event(
            events,
            repo=repo,
            payload=payload,
            source_event_id=f"release_added:{rid}",
            refetched_at=refetched_at,
        )

    if (
        recorded_view is not None
        and recorded_view.repo_identity
        and refetched_view.repo_identity
    ):
        prior_norm = normalize_repo_identity(recorded_view.repo_identity, repo_key=repo)
        new_norm = normalize_repo_identity(refetched_view.repo_identity, repo_key=repo)
        if prior_norm != new_norm:
            payload = IntegrityEventPayload(
                subtype="repo_moved",
                severity="high",
                expected=dict(prior_norm),
                observed=dict(new_norm),
                prior_observed_at=prior_observed_at,
                refetched_at=refetched_at,
            )
            _append_drift_event(
                events,
                repo=repo,
                payload=payload,
                source_event_id="repo_moved",
                refetched_at=refetched_at,
            )

    return events
