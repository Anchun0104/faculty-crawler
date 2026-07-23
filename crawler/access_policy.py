from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

from crawler.models import PageAssessment, RecommendedAction


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float
    reason: str


def retry_decision(
    *,
    attempt: int,
    assessment: PageAssessment,
    retry_after: str | None,
    now: datetime,
) -> RetryDecision:
    if assessment.action is not RecommendedAction.RETRY_LATER:
        return RetryDecision(False, 0, assessment.action.value)
    if attempt >= 3:
        return RetryDecision(False, 0, "retry_limit")

    delay = float(2**attempt)
    retry_after_delay = _retry_after_delay(retry_after, now)
    if retry_after_delay is not None:
        delay = max(delay, retry_after_delay)
    return RetryDecision(True, delay, "bounded_retry")


def _retry_after_delay(retry_after: str | None, now: datetime) -> float | None:
    if not retry_after:
        return None

    try:
        delay = float(retry_after)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
        except (IndexError, TypeError, ValueError, OverflowError):
            return None
        if retry_at is None:
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        delay = (retry_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds()

    return delay if isfinite(delay) and delay >= 0 else None
