from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from crawler.parsers import FacultyRecord, TitlePendingRecord


class TaskStatus(StrEnum):
    PENDING = "pending"
    FETCHING = "fetching"
    EXPANDING = "expanding"
    PARSING = "parsing"
    RETRY_WAIT = "retry_wait"
    VERIFICATION_REQUIRED = "verification_required"
    READY_TO_RESUME = "ready_to_resume"
    SUCCEEDED = "succeeded"
    REVIEW_RECOMMENDED = "review_recommended"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PageKind(StrEnum):
    DIRECTORY = "directory"
    DELAYED_SHELL = "delayed_shell"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    HUMAN_VERIFICATION = "human_verification"
    LOGIN_REQUIRED = "login_required"
    ACCESS_DENIED = "access_denied"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class RecommendedAction(StrEnum):
    PARSE = "parse"
    WAIT_FOR_CONTENT = "wait_for_content"
    RETRY_LATER = "retry_later"
    QUEUE_VERIFICATION = "queue_verification"
    RETRY_OR_STOP = "retry_or_stop"
    STOP_WITH_DIAGNOSTICS = "stop_with_diagnostics"


@dataclass(frozen=True)
class PageEvidence:
    code: str
    detail: str


@dataclass(frozen=True)
class PageAssessment:
    kind: PageKind
    action: RecommendedAction
    evidence: tuple[PageEvidence, ...] = ()


@dataclass(frozen=True)
class CrawlOutcome:
    status: TaskStatus
    records: tuple[FacultyRecord, ...] = ()
    pending_titles: tuple[TitlePendingRecord, ...] = ()
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DynamicTrace:
    action: str
    rounds: int
    additions: tuple[int, ...]
    stop_reason: str
