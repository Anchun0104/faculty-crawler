from __future__ import annotations

from crawler.models import PageAssessment, PageEvidence, PageKind, RecommendedAction


def classify_page(*, url: str, status: int | None, title: str, text: str, html_length: int, candidate_count: int) -> PageAssessment:
    del url
    haystack = f"{title}\n{text}".casefold()
    if candidate_count > 0:
        return PageAssessment(PageKind.DIRECTORY, RecommendedAction.PARSE, (PageEvidence("candidates", str(candidate_count)),))
    if status == 429 or "too many requests" in haystack or "rate limit" in haystack:
        return PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER, (PageEvidence("rate_limit", str(status or "text")),))
    challenge_markers = ("verify you are human", "security check", "just a moment", "captcha", "turnstile")
    if any(marker in haystack for marker in challenge_markers):
        return PageAssessment(PageKind.HUMAN_VERIFICATION, RecommendedAction.QUEUE_VERIFICATION, (PageEvidence("challenge_text", title or "matched body text"),))
    login_markers = ("sign in to continue", "log in to continue", "login required")
    if any(marker in haystack for marker in login_markers):
        return PageAssessment(PageKind.LOGIN_REQUIRED, RecommendedAction.QUEUE_VERIFICATION, (PageEvidence("login_text", title or "matched body text"),))
    if status == 403 or "access denied" in haystack or "forbidden" in haystack:
        return PageAssessment(PageKind.ACCESS_DENIED, RecommendedAction.RETRY_OR_STOP, (PageEvidence("access_denied", str(status or "text")),))
    if status is not None and 500 <= status < 600:
        return PageAssessment(PageKind.TEMPORARY_FAILURE, RecommendedAction.RETRY_LATER, (PageEvidence("server_error", str(status)),))
    if not html_length:
        return PageAssessment(PageKind.EMPTY, RecommendedAction.RETRY_LATER, (PageEvidence("empty", "0"),))
    if html_length < 100:
        return PageAssessment(PageKind.DELAYED_SHELL, RecommendedAction.WAIT_FOR_CONTENT, (PageEvidence("short_html", str(html_length)),))
    return PageAssessment(PageKind.UNKNOWN, RecommendedAction.STOP_WITH_DIAGNOSTICS, (PageEvidence("no_candidates", str(candidate_count)),))
