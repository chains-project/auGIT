from dataclasses import dataclass
from datetime import datetime
from typing import Any

from augit.integrity import compare_refetch_views
from augit.integrity_baseline import (
    audit_log_view_has_content,
    build_view_from_audit_log,
)
from augit.models import EventIn, IntegrityRefetchView, RepoKey
from augit.store import EventStore


@dataclass(frozen=True)
class IntegrityRunResult:
    run_id: int
    integrity_events: list[EventIn]
    summary: dict[str, Any]


def execute_integrity_refetch(
    store: EventStore,
    repo_key: RepoKey,
    refetched_view: IntegrityRefetchView,
    *,
    refetched_at: datetime,
) -> IntegrityRunResult:
    """
    Compare the recorded audit trail against a freshly refetched view.

    The refetched view is also stored in ``integrity_refetches`` as a cache of what
    was observed at ``refetched_at``.
    """
    repo_id = store.ensure_repo(repo_key)
    run_id = store.start_run(repo_id, mode="integrity_refetch")

    all_events: list[EventIn] = []
    summary_parts: dict[str, Any] = {}

    recorded_view = build_view_from_audit_log(store, repo_key)
    if not audit_log_view_has_content(recorded_view):
        summary_parts["skipped"] = "no_recorded_subjects"
    else:
        drift_events = compare_refetch_views(
            repo_key,
            recorded_view,
            refetched_view,
            prior_observed_at=None,
            refetched_at=refetched_at,
        )
        all_events.extend(drift_events)
        summary_parts["drift_events_detected"] = len(drift_events)

    inserted_events: list[EventIn] = []
    for event in all_events:
        if store.append_event(run_id, event) is not None:
            inserted_events.append(event)

    summary: dict[str, Any] = {
        "integrity_events_emitted": len(inserted_events),
        "drift_events_detected": len(all_events),
        "branches": list(refetched_view.branch_reachability.keys()),
        "tags": len(refetched_view.tag_targets),
        "pull_requests": len(refetched_view.pull_requests),
        "releases": len(refetched_view.releases),
        **summary_parts,
    }
    store.insert_integrity_refetch(
        repo_key,
        run_id=run_id,
        refetched_at=refetched_at,
        subjects=refetched_view.model_dump(mode="json"),
        summary=summary,
    )
    store.finish_run(run_id)

    return IntegrityRunResult(
        run_id=run_id, integrity_events=inserted_events, summary=summary
    )
