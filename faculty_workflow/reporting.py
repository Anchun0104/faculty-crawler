from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from faculty_workflow.database import WorkflowDatabase


class RunReporter:
    """Build a bounded machine-readable diagnostic report for a completed task."""

    def __init__(self, *, max_events_per_kind: int = 20) -> None:
        self.max_events_per_kind = max(1, max_events_per_kind)

    def build(self, database: WorkflowDatabase, task_id: str) -> dict[str, Any]:
        task = database.get_task(task_id)
        candidates = database.list_candidates(task_id)
        sources = database.list_sources(task_id)
        outcomes = Counter(str(row["status"] or "unknown") for row in candidates)
        reasons = Counter(
            reason
            for row in candidates
            for reason in str(row["review_reason"] or "").split(";")
            if reason
        )
        failed = [
            {
                "url": str(row["url"] or ""),
                "source_type": str(row["source_type"] or "unknown"),
                "reason": str(row["failure_reason"] or "unknown"),
            }
            for row in sources
            if str(row["fetch_state"] or "") == "failed" or row["failure_reason"]
        ][: self.max_events_per_kind]
        source_types = Counter(str(row["source_type"] or "unknown") for row in sources)
        failed_profiles = sum(1 for item in failed if item["source_type"] == "person_profile")
        signals: list[dict[str, Any]] = []
        if reasons and reasons.most_common(1)[0][0] == "missing_email":
            signals.append({
                "code": "email_missing_dominates_review",
                "evidence": {"missing_email": reasons["missing_email"], "review": outcomes["review"]},
                "suggested_focus": "Inspect literal email decoders and official profile availability.",
            })
        if failed and failed_profiles * 2 >= len(failed):
            signals.append({
                "code": "profile_timeouts_dominate",
                "evidence": {"failed_profiles": failed_profiles, "failed_sources": len(failed)},
                "suggested_focus": "Inspect personal-page timeout and eligibility rules.",
            })
        if any(row["stop_reason"] for row in sources) or failed:
            signals.append({
                "code": "directory_coverage_incomplete",
                "evidence": {"failed_sources": len(failed)},
                "suggested_focus": "Inspect pagination, dynamic expansion, and failed directory sources.",
            })
        return {
            "schema_version": 1,
            "run": {"task_id": task_id, "workflow_status": str(task["status"]), "discipline": str(task["discipline"])},
            "outcomes": {status: outcomes[status] for status in ("accepted", "review", "unresolved", "rejected")},
            "sources": {"total": len(sources), "by_type": dict(source_types), "failed": len(failed)},
            "top_review_reasons": dict(reasons.most_common()),
            "diagnostics": {"failed_sources": failed},
            "optimization_signals": signals,
            "review_generations": [dict(row) for row in database.list_review_generations(task_id)],
        }
