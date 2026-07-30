from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from http import HTTPStatus
from typing import Callable, Mapping
from urllib.parse import urlparse

from openpyxl import Workbook

from crawler.access_policy import retry_decision
from crawler.consent import dismiss_cookie_overlay
from crawler.diagnostics_export import export_records
from crawler.dynamic_loader import _PlaywrightDynamicAdapter, collect_dynamic_snapshots
from crawler.models import (
    CrawlOutcome,
    DynamicTrace,
    PageAssessment,
    PageKind,
    RecommendedAction,
    TaskStatus,
)
from crawler.page_state import classify_page
from crawler.parsers import (
    FacultyRecord,
    TitlePendingRecord,
    _normalize_record_profile_url,
    find_next_directory_page_url,
    normalized_person_profile_urls,
    parse_faculty_page,
    remove_duplicates,
    remove_duplicate_title_pending_records,
)
from crawler.verification import _canonical_url_hostname, scope_storage_state
from crawler.title_classifier import StaffClassification, TitleClassifier
from crawler.title_pipeline import TitlePipeline
from crawler.translation import LibreTranslateClient
from crawler.translation_settings import TranslationSettings


logger = logging.getLogger(__name__)
MIN_HTML_LENGTH = 100


def _classification_summary(records: list[FacultyRecord]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for record in records:
        key = record.staff_classification
        summary[key] = summary.get(key, 0) + 1
    return summary


class EmptyFetchError(RuntimeError):
    pass


class TransientLoadError(RuntimeError):
    """A navigation failure that is safe to retry with the bounded policy."""


@dataclass(frozen=True)
class _LoadResult:
    status: int | None
    html: str
    retry_after: str | None = None
    title: str = ""
    text: str = ""
    final_url: str | None = None
    text_available: bool = True


@dataclass(frozen=True)
class _DynamicResult:
    snapshots: list[str]
    traces: list[DynamicTrace]
    final_html: str
    final_url: str


@dataclass(frozen=True)
class _DynamicNavigation:
    html: str
    final_url: str
    status: int | None = None
    title: str = ""
    text: str = ""


class FacultyCrawler:
    def __init__(
        self,
        timeout: int = 30000,
        headless: bool = True,
        *,
        session_store=None,
        playwright_factory: Callable[[], object] | None = None,
        title_pipeline: TitlePipeline | None = None,
        translation_settings: TranslationSettings | None = None,
    ) -> None:
        self.timeout = timeout
        self.headless = headless
        self.session_store = session_store
        self._playwright_factory = playwright_factory
        self.title_pipeline = title_pipeline or TitlePipeline(
            TitleClassifier(),
            (translation_settings or TranslationSettings()).create_client(),
        )
        self.last_diagnostics: dict[str, object] = {}
        self.title_pending_records: list[TitlePendingRecord] = []
        self.review_records: list[FacultyRecord] = []
        self.excluded_records: list[FacultyRecord] = []
        self.classification_summary: dict[str, int] = {}
        self._terminal_status: TaskStatus | None = None

    def export_review_records(self, path: str | Path, format: str | None = None) -> Path:
        return export_records(self.review_records, path, format)

    def export_excluded_records(self, path: str | Path, format: str | None = None) -> Path:
        return export_records(self.excluded_records, path, format)

    def crawl(self, url: str) -> list[FacultyRecord]:
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run 'pip install -r requirements.txt' "
                "and 'playwright install chromium'."
            ) from exc

        logger.info("Opening faculty directory: %s", url)
        context_options, session_diagnostic = self._session_context_options(url)
        try:
            factory = self._playwright_factory or sync_playwright
            with factory() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                context = None
                try:
                    try:
                        context = browser.new_context(**context_options)
                    except Exception:
                        logger.error("Browser context failed: code=context_creation_failed")
                        raise RuntimeError("browser_context_failed") from None
                    page = context.new_page()
                    page.set_default_timeout(self.timeout)
                    dynamic_adapter = _PlaywrightDynamicAdapter(page, timeout_ms=min(self.timeout, 1000))

                    def capture_page(response: object | None = None) -> Mapping[str, object]:
                        html = page.content()
                        text_available = True
                        try:
                            visible_text = page.locator("body").inner_text()
                        except PlaywrightError:
                            visible_text = ""
                            text_available = False
                        return {
                            "status": getattr(response, "status", None),
                            "html": html,
                            "retry_after": response.headers.get("retry-after") if response else None,
                            "title": page.title(),
                            "text": visible_text,
                            "text_available": text_available,
                            "final_url": page.url,
                        }

                    def load_page(page_url: str) -> Mapping[str, object]:
                        try:
                            response = page.goto(page_url, wait_until="domcontentloaded", timeout=self.timeout)
                        except PlaywrightTimeoutError as exc:
                            raise TransientLoadError("navigation timeout") from exc
                        except PlaywrightError as exc:
                            if "net::err_" in str(exc).lower():
                                raise TransientLoadError("temporary network navigation failure") from exc
                            raise
                        html = _settle_page_content(
                            page,
                            page_url,
                            timeout_ms=self.timeout,
                            timeout_error=PlaywrightTimeoutError,
                        )
                        result = dict(capture_page(response))
                        result["html"] = html
                        return result

                    def dynamic_action(action: str, page_url: str, current_profile_urls: set[str]):
                        html = _interact_with_dynamic_result_page(
                            page,
                            action,
                            page_url,
                            current_profile_urls,
                            self.timeout,
                        )
                        if html is None:
                            return None
                        result = dict(capture_page())
                        result["html"] = html
                        return result

                    def collect_snapshots(page_url: str, initial_html: str):
                        snapshots, traces = collect_dynamic_snapshots(
                            dynamic_adapter,
                            page_url,
                            initial_html,
                            timeout_ms=self.timeout,
                        )
                        return {
                            "snapshots": snapshots,
                            "traces": traces,
                            "final_html": page.content(),
                            "final_url": page.url,
                        }

                    records = self._crawl_pages(
                        url,
                        load_page,
                        render_attempt=lambda _url: capture_page(),
                        dynamic_action=dynamic_action,
                        dynamic_collector=collect_snapshots,
                        consent_action=lambda: dismiss_cookie_overlay(page),
                    )
                finally:
                    _close_browser_resources(context, browser)
        except PlaywrightError as exc:
            raise RuntimeError(f"Failed to load faculty directory: {exc}") from exc

        if session_diagnostic is not None:
            self.last_diagnostics["Session state"] = session_diagnostic

        return records

    def _session_context_options(
        self,
        url: str,
    ) -> tuple[dict[str, object], str | None]:
        if self.session_store is None:
            return {}, None
        try:
            hostname, is_ipv6 = _canonical_url_hostname(url)
        except ValueError:
            return {}, "session_hostname_invalid"
        if is_ipv6:
            logger.info("Session state skipped: code=ipv6_session_skipped")
            return {}, "ipv6_session_skipped"
        try:
            saved = self.session_store.load(hostname)
        except Exception:
            logger.warning("Session state unavailable: code=session_load_unavailable")
            return {}, "session_load_unavailable"
        if saved is None:
            return {}, "session_state_absent"
        try:
            state = scope_storage_state(saved, hostname)
        except (TypeError, ValueError):
            try:
                self.session_store.clear_site(hostname)
            except Exception:
                logger.warning("Session cleanup unavailable: code=session_cleanup_unavailable")
            logger.warning("Session state invalid: code=session_state_invalid")
            return {}, "session_state_invalid"
        return {"storage_state": state}, None

    def _outcome_from_records(self, records: list[FacultyRecord]) -> CrawlOutcome:
        status = self._terminal_status or (TaskStatus.SUCCEEDED if records else TaskStatus.FAILED)
        if (
            self._terminal_status is None
            and records
            and self.last_diagnostics.get("Failure stage") == "low_coverage_warning"
        ):
            status = TaskStatus.REVIEW_RECOMMENDED
        return CrawlOutcome(
            status,
            tuple(records),
            tuple(self.title_pending_records),
            dict(self.last_diagnostics),
        )

    def crawl_outcome(self, url: str) -> CrawlOutcome:
        return self._outcome_from_records(self.crawl(url))

    def parse_fetched_directory(
        self,
        url: str,
        html: str,
        fetch_status: int | None,
    ) -> list[FacultyRecord]:
        """Parse a directory snapshot without opening a second browser session."""
        return self._parse_fetched_html(url, html, fetch_status)

    def _crawl_pages(
        self,
        url: str,
        load_page: Callable[[str], object] | None = None,
        load_dynamic_pages: Callable[[str, str], list[str]] | None = None,
        *,
        load_attempt: Callable[[str], object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        render_wait: Callable[[float], None] = time.sleep,
        render_attempt: Callable[[str], object] | None = None,
        dynamic_action: Callable[[str, str, set[str]], object] | None = None,
        dynamic_collector: Callable[[str, str], object] | None = None,
        consent_action: Callable[[], str | None] | None = None,
    ) -> list[FacultyRecord]:
        if load_attempt is not None:
            loader = lambda page_url: _coerce_load_result(load_attempt(page_url), status_first=True)
        elif load_page is not None:
            loader = lambda page_url: _coerce_load_result(load_page(page_url), status_first=False)
        else:
            raise TypeError("load_page or load_attempt is required")
        current_url = url
        visited: set[str] = set()
        records: list[FacultyRecord] = []
        pending_records: list[TitlePendingRecord] = []
        self.title_pending_records = []
        self.review_records = []
        self.excluded_records = []
        self.classification_summary = {}
        self._terminal_status = None
        dynamic_pages_visited = 0
        retry_attempts = 0
        retry_traces: list[dict[str, object]] = []
        assessments: list[dict[str, str]] = []
        consent_label: str | None = None
        consent_checked = False
        dynamic_traces: list[DynamicTrace] = []
        stop_crawl = False
        visible_text_available: bool | None = None

        while current_url and len(visited) < 100:
            visit_key = _pagination_visit_key(current_url)
            if visit_key in visited:
                break
            visited.add(visit_key)
            retry_attempt = 0
            render_polls = 0
            loaded: _LoadResult | None = None
            while True:
                try:
                    raw_result = (
                        render_attempt(current_url)
                        if render_polls and render_attempt is not None
                        else loader(current_url)
                    )
                    loaded = _coerce_load_result(
                        raw_result,
                        status_first=load_attempt is not None or render_polls > 0,
                    )
                    visible_text_available = loaded.text_available
                except (TransientLoadError, TimeoutError, ConnectionError):
                    loaded = None
                    assessment = PageAssessment(
                        PageKind.TEMPORARY_FAILURE,
                        RecommendedAction.RETRY_LATER,
                    )
                    assessments.append({"kind": assessment.kind.value, "action": assessment.action.value})
                    decision = retry_decision(
                        attempt=retry_attempt,
                        assessment=assessment,
                        retry_after=None,
                        now=datetime.now(timezone.utc),
                    )
                    if not decision.should_retry:
                        self._set_fetch_failure_diagnostics(
                            url=current_url,
                            fetch_status=None,
                            html_length=0,
                            reason="Transient page load failed after bounded retries",
                        )
                        break
                    retry_traces.append(
                        _retry_trace(None, retry_attempt, decision.delay_seconds, decision.reason)
                    )
                    sleep(decision.delay_seconds)
                    retry_attempts += 1
                    retry_attempt += 1
                    render_polls = 0
                    continue

                candidate_count = _candidate_count(loaded.html, loaded.final_url or current_url)
                assessment = classify_page(
                    url=loaded.final_url or current_url,
                    status=loaded.status,
                    title=loaded.title,
                    text=loaded.text,
                    html_length=len(loaded.html or ""),
                    candidate_count=candidate_count,
                )
                assessments.append({"kind": assessment.kind.value, "action": assessment.action.value})
                if assessment.action is RecommendedAction.QUEUE_VERIFICATION:
                    self._terminal_status = TaskStatus.VERIFICATION_REQUIRED
                    break
                if assessment.action is RecommendedAction.WAIT_FOR_CONTENT and render_polls < 3:
                    render_wait(0.25)
                    render_polls += 1
                    continue
                decision = retry_decision(
                    attempt=retry_attempt,
                    assessment=assessment,
                    retry_after=loaded.retry_after,
                    now=datetime.now(timezone.utc),
                )
                if not decision.should_retry:
                    break
                retry_traces.append(
                    _retry_trace(loaded.status, retry_attempt, decision.delay_seconds, decision.reason)
                )
                sleep(decision.delay_seconds)
                retry_attempts += 1
                retry_attempt += 1
                render_polls = 0

            if loaded is None:
                stop_crawl = True
                break
            html, fetch_status = loaded.html, loaded.status
            if self._terminal_status is TaskStatus.VERIFICATION_REQUIRED:
                self._set_fetch_failure_diagnostics(
                    url=loaded.final_url or current_url,
                    fetch_status=fetch_status,
                    html_length=len(html or ""),
                    reason="Human verification required",
                )
                break
            if (
                consent_action is not None
                and not consent_checked
                and (fetch_status is None or fetch_status < 400)
            ):
                consent_label = consent_action()
                consent_checked = True

            live_html = html
            live_url = loaded.final_url or current_url
            live_rounds = 0
            allow_dynamic = fetch_status is None or fetch_status < 400
            while live_html and live_rounds < 100:
                if allow_dynamic and dynamic_action is not None and len(live_html) >= MIN_HTML_LENGTH:
                    expanded = _coerce_dynamic_navigation(
                        dynamic_action(
                            "largest_page_size",
                            live_url,
                            normalized_person_profile_urls(live_html, live_url),
                        ),
                        live_url,
                    )
                    if expanded is not None:
                        live_html, live_url = expanded.html, expanded.final_url

                rendered_pages = [(live_html, live_url)]
                if allow_dynamic and load_dynamic_pages is not None:
                    legacy_pages = load_dynamic_pages(live_url, live_html)
                    rendered_pages.extend((page_html, live_url) for page_html in legacy_pages)
                    dynamic_pages_visited += len(legacy_pages)

                final_live_html = rendered_pages[-1][0]
                final_live_url = live_url
                if allow_dynamic and dynamic_collector is not None and len(live_html) >= MIN_HTML_LENGTH:
                    collection = _coerce_dynamic_result(
                        dynamic_collector(live_url, live_html),
                        live_html,
                        live_url,
                    )
                    rendered_pages.extend(
                        (snapshot, collection.final_url)
                        for snapshot in collection.snapshots
                    )
                    dynamic_pages_visited += len(collection.snapshots)
                    dynamic_traces.extend(collection.traces)
                    final_live_html = collection.final_html
                    final_live_url = collection.final_url
                    verification_found = any(
                        trace.stop_reason == "verification_required"
                        for trace in collection.traces
                    )
                    if (
                        not verification_found
                        and all(
                            (page_html, page_url) != (final_live_html, final_live_url)
                            for page_html, page_url in rendered_pages
                        )
                    ):
                        rendered_pages.append((final_live_html, final_live_url))

                for rendered_html, rendered_url in rendered_pages:
                    page_records = self._parse_fetched_html(
                        url=rendered_url,
                        html=rendered_html,
                        fetch_status=fetch_status,
                    )
                    records.extend(page_records)
                    pending_records.extend(self.title_pending_records)

                if any(
                    trace.stop_reason == "verification_required"
                    for trace in dynamic_traces
                ):
                    self._terminal_status = TaskStatus.VERIFICATION_REQUIRED
                    stop_crawl = True
                    break

                if not allow_dynamic:
                    current_url = ""
                    break

                next_url = find_next_directory_page_url(final_live_html, final_live_url)
                if next_url:
                    current_url = next_url
                    break

                if dynamic_action is None:
                    current_url = ""
                    break
                next_state = _coerce_dynamic_navigation(
                    dynamic_action(
                        "next",
                        final_live_url,
                        normalized_person_profile_urls(final_live_html, final_live_url),
                    ),
                    final_live_url,
                )
                if next_state is None:
                    current_url = ""
                    break
                next_assessment = classify_page(
                    url=next_state.final_url,
                    status=next_state.status,
                    title=next_state.title,
                    text=next_state.text,
                    html_length=len(next_state.html),
                    candidate_count=_candidate_count(next_state.html, next_state.final_url),
                )
                assessments.append(
                    {"kind": next_assessment.kind.value, "action": next_assessment.action.value}
                )
                if next_assessment.action is RecommendedAction.QUEUE_VERIFICATION:
                    self._terminal_status = TaskStatus.VERIFICATION_REQUIRED
                    self._set_dynamic_next_failure(
                        next_state,
                        "Human verification required after dynamic next",
                    )
                    stop_crawl = True
                    break
                if next_assessment.action is not RecommendedAction.PARSE:
                    self._terminal_status = (
                        TaskStatus.REVIEW_RECOMMENDED if records else TaskStatus.FAILED
                    )
                    self._set_dynamic_next_failure(
                        next_state,
                        f"Dynamic next stopped: {next_assessment.kind.value}",
                    )
                    stop_crawl = True
                    break
                next_html, next_live_url = next_state.html, next_state.final_url
                old_profiles = normalized_person_profile_urls(final_live_html, final_live_url)
                new_profiles = normalized_person_profile_urls(next_html, next_live_url)
                if not new_profiles or not new_profiles - old_profiles:
                    current_url = ""
                    break
                live_html, live_url = next_html, next_live_url
                live_rounds += 1
                dynamic_pages_visited += 1

            if stop_crawl:
                break
            if not current_url or _pagination_visit_key(current_url) in visited:
                break

        unique_records = remove_duplicates(records)
        self.review_records = remove_duplicates(self.review_records)
        self.excluded_records = remove_duplicates(self.excluded_records)
        complete_profile_urls = {
            _normalize_record_profile_url(record.profile_url)
            for record in unique_records
            if record.profile_url
        }
        self.title_pending_records = [
            record
            for record in remove_duplicate_title_pending_records(pending_records)
            if _normalize_record_profile_url(record.profile_url) not in complete_profile_urls
        ]
        included_keys = {
            _normalize_record_profile_url(record.profile_url)
            for record in unique_records
        }
        self.review_records = [
            record
            for record in self.review_records
            if _normalize_record_profile_url(record.profile_url) not in included_keys
        ]
        self.excluded_records = [
            record
            for record in self.excluded_records
            if _normalize_record_profile_url(record.profile_url) not in included_keys
        ]
        self.classification_summary = _classification_summary(
            [*unique_records, *self.review_records, *self.excluded_records]
        )
        self.last_diagnostics["Title classification summary"] = dict(self.classification_summary)
        self.last_diagnostics["Title review records"] = len(self.review_records)
        self.last_diagnostics["Title excluded records"] = len(self.excluded_records)
        pages_visited = len(visited) + dynamic_pages_visited
        self.last_diagnostics["Pagination pages visited"] = pages_visited
        self.last_diagnostics["Number of parsed records"] = len(unique_records)
        self.last_diagnostics["Title pending records"] = len(self.title_pending_records)
        self.last_diagnostics["Page assessment"] = assessments
        self.last_diagnostics["Retry attempts"] = retry_attempts
        self.last_diagnostics["Retry traces"] = retry_traces
        self.last_diagnostics["Consent action"] = consent_label
        self.last_diagnostics["Dynamic traces"] = [_trace_diagnostics(trace) for trace in dynamic_traces]
        self.last_diagnostics["Dynamic stop reason"] = dynamic_traces[-1].stop_reason if dynamic_traces else None
        self.last_diagnostics["Visible text captured"] = visible_text_available
        logger.info("Pagination pages visited: %s", pages_visited)
        return unique_records

    def _set_dynamic_next_failure(
        self,
        navigation: _DynamicNavigation,
        reason: str,
    ) -> None:
        self._set_fetch_failure_diagnostics(
            url=navigation.final_url,
            fetch_status=navigation.status,
            html_length=len(navigation.html),
            reason=reason,
        )
        self.last_diagnostics["Failure stage"] = "dynamic_next"

    def _parse_fetched_html(self, url: str, html: str, fetch_status: int | None) -> list[FacultyRecord]:
        self.title_pending_records = []
        html_length = len(html or "")
        if fetch_status is not None and fetch_status >= 400:
            self._set_fetch_failure_diagnostics(
                url=url,
                fetch_status=fetch_status,
                html_length=html_length,
                reason=_http_error_reason(fetch_status),
            )
            self._log_diagnostics()
            return []

        if not html or not html.strip():
            self._set_fetch_failure_diagnostics(
                url=url,
                fetch_status=fetch_status,
                html_length=html_length,
                reason="Empty or too short HTML response",
            )
            self._log_diagnostics()
            raise EmptyFetchError("Empty response after fetch")

        if html_length < MIN_HTML_LENGTH:
            self._set_fetch_failure_diagnostics(
                url=url,
                fetch_status=fetch_status,
                html_length=html_length,
                reason="Empty or too short HTML response",
            )
            self._log_diagnostics()
            return []

        result = parse_faculty_page(html, url)
        language_hint = _page_language_hint(html)
        unique_records = self._process_title_classifications(
            remove_duplicates(result.records),
            url,
            language_hint,
        )
        self.title_pending_records = remove_duplicate_title_pending_records(result.title_pending_records)
        self.last_diagnostics = {
            "URL": url,
            "Fetch status": fetch_status,
            "HTML length": html_length,
            "Detected page type": result.page_type,
            "Number of candidate records": result.candidate_count,
            "Number of parsed records": len(unique_records),
            "Title pending records": len(self.title_pending_records),
            "Title classification summary": dict(self.classification_summary),
            "Title review records": len(self.review_records),
            "Title excluded records": len(self.excluded_records),
            "Low coverage debug": (
                f"possible person links={result.possible_person_link_count}, "
                f"candidate containers={result.candidate_count}, "
                f"fallback_person_links_count={result.fallback_person_links_count}, "
                f"fallback_candidates_count={result.fallback_candidates_count}, "
                f"heading_person_candidates_count={result.heading_person_candidates_count}, "
                f"heading_records_parsed={result.heading_records_parsed}, "
                f"heading_card_candidates_count={result.heading_card_candidates_count}, "
                f"generic_profile_links_count={result.generic_profile_links_count}, "
                f"role_group_count={result.role_group_count}, "
                f"person_rows_detected={result.person_rows_detected}, "
                f"faculty_profile_links_detected={result.faculty_profile_links_detected}, "
                f"unique_profile_links_count={result.unique_profile_links_count}, "
                f"local_person_blocks_created={result.local_person_blocks_created}, "
                f"duplicate_profile_links_count={result.duplicate_profile_links_count}, "
                f"excluded_section_count={result.excluded_section_count}, "
                f"wrapper_person_links_count={result.wrapper_person_links_count}, "
                f"segmented_person_blocks_count={result.segmented_person_blocks_count}, "
                f"recovered_profile_links_count={result.recovered_profile_links_count}, "
                f"cards_missing_profile_url_count={result.cards_missing_profile_url_count}, "
                f"card_recovered_profile_links_count={result.card_recovered_profile_links_count}, "
                f"table_rows_detected={result.table_rows_detected}, "
                f"table_rows_parsed={result.table_rows_parsed}"
            ),
            "Fallback person link debug": result.fallback_link_debug,
            "Heading person link debug": result.heading_person_link_debug,
            "Card profile link debug": result.card_profile_link_debug,
            "Heading card debug": result.heading_card_debug,
            "Role group debug": result.role_group_debug,
            "Segmented person block debug": result.segmented_person_debug,
            "Pagination pages visited": 1,
            "Detected table headers": result.table_headers_debug,
            "Detected section headings": result.section_headings_debug,
            "Top href patterns": result.href_patterns_debug,
            "Dropped candidate debug": result.dropped_candidate_debug,
            "Failure stage": result.failure_stage,
            "Failure reason": "",
        }
        self._log_diagnostics()
        logger.info("Extracted %s faculty records.", len(unique_records))
        return unique_records

    def _process_title_classifications(
        self,
        records: list[FacultyRecord],
        source_url: str,
        language_hint: str,
    ) -> list[FacultyRecord]:
        included: list[FacultyRecord] = []
        for record in records:
            processed = self.title_pipeline.process(record.title, language_hint=language_hint)
            classification = processed.classification
            enriched = replace(
                record,
                title_translated=processed.title_translated,
                title_language=processed.title_language,
                staff_classification=classification.classification.value,
                academic_track=classification.academic_track.value,
                affiliation_status=classification.affiliation_status.value,
                classification_reason=classification.reason,
                matched_rule=classification.matched_rule,
                confidence_tier=classification.confidence.value,
                translation_status=processed.translation_status,
                translation_engine=processed.translation_engine,
                classification_rules_version=processed.rules_version,
                source_url=source_url,
            )
            key = classification.classification.value
            self.classification_summary[key] = self.classification_summary.get(key, 0) + 1
            if classification.classification is StaffClassification.INCLUDE:
                included.append(enriched)
            elif classification.classification is StaffClassification.EXCLUDE:
                self.excluded_records.append(enriched)
            else:
                self.review_records.append(enriched)
        return included

    def _set_fetch_failure_diagnostics(
        self,
        url: str,
        fetch_status: int | None,
        html_length: int,
        reason: str,
    ) -> None:
        self.last_diagnostics = {
            "URL": url,
            "Fetch status": fetch_status,
            "HTML length": html_length,
            "Detected page type": "unknown",
            "Number of candidate records": 0,
            "Number of parsed records": 0,
            "Failure stage": "fetch",
            "Failure reason": reason,
        }

    def _log_diagnostics(self) -> None:
        for label, value in self.last_diagnostics.items():
            logger.info("%s: %s", label, value)


def _page_language_hint(html: str) -> str:
    match = re.search(r"<html\b[^>]*\blang\s*=\s*[\"']?([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)?)", html, re.IGNORECASE)
    if match is None:
        return ""
    return match.group(1).casefold().split("-", 1)[0]


def _coerce_load_result(value: object, *, status_first: bool) -> _LoadResult:
    if isinstance(value, _LoadResult):
        return value
    if isinstance(value, Mapping):
        html = str(value.get("html") or "")
        has_visible_text = "text" in value
        return _LoadResult(
            status=value.get("status") if isinstance(value.get("status"), int) else None,
            html=html,
            retry_after=str(value["retry_after"]) if value.get("retry_after") is not None else None,
            title=str(value.get("title") or ""),
            text=str(value.get("text") or "") if has_visible_text else "",
            final_url=str(value["final_url"]) if value.get("final_url") else None,
            text_available=bool(value.get("text_available", has_visible_text)),
        )
    if isinstance(value, tuple) and len(value) == 2:
        first, second = value
        status, html = (first, second) if status_first else (second, first)
        html_text = str(html or "")
        return _LoadResult(
            status if isinstance(status, int) else None,
            html_text,
            title=_html_title(html_text),
            text=_html_text(html_text),
        )
    raise TypeError("page loader must return a two-item tuple or mapping")


def _coerce_dynamic_navigation(value: object, base_url: str) -> _DynamicNavigation | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _DynamicNavigation(
            value,
            base_url,
            title=_html_title(value),
            text=_html_text(value),
        )
    if isinstance(value, Mapping):
        html = str(value.get("html") or "")
        if not html:
            return None
        return _DynamicNavigation(
            html,
            str(value.get("final_url") or base_url),
            value.get("status") if isinstance(value.get("status"), int) else None,
            str(value.get("title") or ""),
            str(value.get("text") or "") if "text" in value else "",
        )
    raise TypeError("dynamic action must return HTML, a mapping, or None")


def _coerce_dynamic_result(value: object, initial_html: str, base_url: str) -> _DynamicResult:
    if isinstance(value, Mapping):
        snapshots = list(value.get("snapshots") or [])
        traces = list(value.get("traces") or [])
        return _DynamicResult(
            snapshots,
            traces,
            str(value.get("final_html") or (snapshots[-1] if snapshots else initial_html)),
            str(value.get("final_url") or base_url),
        )
    if isinstance(value, tuple) and len(value) == 2:
        snapshots, traces = value
        snapshot_list = list(snapshots)
        return _DynamicResult(
            snapshot_list,
            list(traces),
            snapshot_list[-1] if snapshot_list else initial_html,
            base_url,
        )
    raise TypeError("dynamic collector must return snapshots and traces")


def _retry_trace(
    status_code: int | None,
    attempt: int,
    delay: float,
    reason: str,
) -> dict[str, object]:
    return {
        "status_code": status_code,
        "attempt": attempt,
        "delay": delay,
        "reason": reason,
    }


def _candidate_count(html: str, url: str) -> int:
    if not html or len(html) < MIN_HTML_LENGTH:
        return 0
    return parse_faculty_page(html, url).candidate_count


def _html_title(html: str) -> str:
    summary = _HtmlSummary()
    summary.feed(html or "")
    return " ".join(summary.title_parts).strip()


def _html_text(html: str) -> str:
    summary = _HtmlSummary()
    summary.feed(html or "")
    return " ".join(summary.text_parts).strip()


class _HtmlSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value or self._ignored_depth:
            return
        self.text_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)


def _trace_diagnostics(trace: DynamicTrace) -> dict[str, object]:
    return {
        "action": trace.action,
        "rounds": trace.rounds,
        "additions": list(trace.additions),
        "stop_reason": trace.stop_reason,
    }


def _http_error_reason(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "HTTP Error"
    return f"HTTP {status_code} {phrase}"


def _pagination_visit_key(value: str) -> str:
    parsed = urlparse(value)
    return parsed._replace(fragment="").geturl().lower()


def _collect_dynamic_result_pages(
    initial_html: str,
    base_url: str,
    interact: Callable[[str, set[str]], str | None],
) -> list[str]:
    seen_profile_urls = normalized_person_profile_urls(initial_html, base_url)
    current_profile_urls = seen_profile_urls
    pages: list[str] = []

    largest_page_html = interact("largest_page_size", current_profile_urls)
    if largest_page_html:
        largest_page_urls = normalized_person_profile_urls(largest_page_html, base_url)
        if largest_page_urls - seen_profile_urls:
            pages.append(largest_page_html)
            seen_profile_urls.update(largest_page_urls)
        if largest_page_urls:
            current_profile_urls = largest_page_urls

    for _ in range(100):
        next_page_html = interact("next", current_profile_urls)
        if not next_page_html:
            break
        next_page_urls = normalized_person_profile_urls(next_page_html, base_url)
        if not next_page_urls or not next_page_urls - seen_profile_urls:
            break
        pages.append(next_page_html)
        seen_profile_urls.update(next_page_urls)
        current_profile_urls = next_page_urls

    return pages


def _close_browser_resources(context, browser) -> None:
    failed = False
    if context is not None:
        try:
            context.close()
        except Exception:
            failed = True
            logger.error("Browser cleanup failed: code=context_close_failed")
    try:
        browser.close()
    except Exception:
        failed = True
        logger.error("Browser cleanup failed: code=browser_close_failed")
    if failed:
        raise RuntimeError("browser_cleanup_failed") from None


def _wait_for_rendered_directory_content(
    page: object,
    base_url: str,
    initial_html: str,
    timeout_ms: int,
) -> str:
    latest_html = initial_html
    if parse_faculty_page(latest_html, base_url).candidate_count:
        return latest_html

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(250)
        current_html = page.content()
        if current_html == latest_html:
            continue
        latest_html = current_html
        if parse_faculty_page(latest_html, base_url).candidate_count:
            return latest_html
    return latest_html


def _settle_page_content(
    page: object,
    base_url: str,
    *,
    timeout_ms: int,
    timeout_error: type[BaseException],
) -> str:
    network_idle_timeout = min(timeout_ms, 10000)
    try:
        page.wait_for_load_state("networkidle", timeout=network_idle_timeout)
    except timeout_error:
        logger.warning("Timed out waiting for network idle; waiting for directory content to render.")
        initial_html = page.content()
        return _wait_for_rendered_directory_content(
            page,
            base_url,
            initial_html,
            timeout_ms=max(0, timeout_ms - network_idle_timeout),
        )
    return page.content()


def _interact_with_dynamic_result_page(
    page: object,
    action: str,
    base_url: str,
    current_profile_urls: set[str],
    timeout: int,
) -> str | None:
    if not page.evaluate(_DYNAMIC_RESULT_ACTION_SCRIPT, action):
        return None

    deadline = time.monotonic() + min(timeout, 10000) / 1000
    latest_html = page.content()
    while time.monotonic() < deadline:
        page.wait_for_timeout(250)
        latest_html = page.content()
        if normalized_person_profile_urls(latest_html, base_url) != current_profile_urls:
            return latest_html
    return latest_html


_DYNAMIC_RESULT_ACTION_SCRIPT = r"""
(action) => {
  const attributeText = (element) => element.getAttributeNames()
    .map((name) => `${name} ${element.getAttribute(name) || ''}`)
    .join(' ')
    .toLowerCase();
  const normalizedText = (element) => (
    element.getAttribute('aria-label') ||
    element.getAttribute('title') ||
    element.value ||
    element.textContent ||
    ''
  ).trim().toLowerCase();
  const profilePath = /\/(?:people|person|persona|profiles?|faculty|staff|employees?|researchers?)(?:\/|$)/i;
  const organizationalPath = /\/(?:departments?|faculties|institutes?|research-groups?|centres?|schools?)(?:\/|$)/i;
  const profileUrls = (root) => new Set(
    [...root.querySelectorAll('a[href]')]
      .map((link) => {
        try { return new URL(link.getAttribute('href'), document.baseURI); }
        catch (_) { return null; }
      })
      .filter((url) => url && /^https?:$/.test(url.protocol) && profilePath.test(url.pathname) && !organizationalPath.test(url.pathname))
      .map((url) => `${url.origin}${url.pathname.replace(/\/$/, '')}${url.search}`.toLowerCase())
  );
  const resultScope = (element) => {
    let current = element.parentElement;
    while (current && current !== document.body) {
      if (profileUrls(current).size >= 2) return current;
      current = current.parentElement;
    }
    return null;
  };
  const isDisabled = (element) => {
    let current = element;
    while (current && current !== document.body) {
      const classes = typeof current.className === 'string' ? current.className.toLowerCase() : '';
      if (current.disabled || current.getAttribute('aria-disabled') === 'true' || /(?:^|\s)disabled(?:\s|$)/.test(classes)) return true;
      current = current.parentElement;
    }
    return false;
  };

  if (action === 'largest_page_size') {
    for (const select of document.querySelectorAll('select')) {
      const marker = `${attributeText(select)} ${attributeText(select.parentElement || select)}`;
      const options = [...select.options]
        .map((option) => ({ option, value: Number((option.value || option.textContent || '').trim()) }))
        .filter((item) => Number.isInteger(item.value) && item.value > 0);
      if (options.length < 2 || !/(?:page|item|result|limit|size|per-page)/.test(marker) || !resultScope(select)) continue;
      const largest = options.reduce((best, item) => item.value > best.value ? item : best);
      if (String(select.value) === String(largest.option.value)) return false;
      select.value = largest.option.value;
      select.dispatchEvent(new Event('input', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }

    const groups = new Map();
    for (const element of document.querySelectorAll('label, button, a, [role="button"], input[type="radio"]')) {
      const rawValue = (
        element.getAttribute('uib-btn-radio') || element.value || element.textContent || ''
      ).trim().replace(/^['"]|['"]$/g, '');
      if (!/^\d+$/.test(rawValue) || !element.parentElement) continue;
      const group = element.parentElement;
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push({ element, value: Number(rawValue) });
    }
    const eligible = [...groups.entries()]
      .filter(([group, items]) => {
        const marker = `${attributeText(group)} ${items.map(({ element }) => attributeText(element)).join(' ')}`;
        return items.length >= 2 && /(?:page|item|result|limit|size|per-page)/.test(marker) && resultScope(group);
      })
      .flatMap(([, items]) => items);
    if (!eligible.length) return false;
    const target = eligible.reduce((best, item) => item.value > best.value ? item : best).element;
    const classes = typeof target.className === 'string' ? target.className.toLowerCase() : '';
    if (target.checked || target.getAttribute('aria-pressed') === 'true' || /(?:active|btn-primary)/.test(classes)) return false;
    target.click();
    return true;
  }

  if (action === 'next') {
    const nextLabels = new Set(['next', 'suivant', 'weiter', 'successivo', 'seguente', 'siguiente', 'próximo', 'proximo']);
    for (const element of document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]')) {
      if (!nextLabels.has(normalizedText(element)) || isDisabled(element)) continue;
      const rawHref = element.getAttribute('href');
      if (rawHref && rawHref !== '#' && !rawHref.toLowerCase().startsWith('javascript:')) continue;
      let pagination = element.parentElement;
      while (pagination && pagination !== document.body) {
        if (pagination.tagName === 'NAV' || /(?:pagination|pager)/.test(attributeText(pagination))) break;
        pagination = pagination.parentElement;
      }
      if (!pagination || pagination === document.body || !resultScope(pagination)) continue;
      element.click();
      return true;
    }
  }
  return false;
}
"""


def export_to_excel(records: list[FacultyRecord], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Faculty"
    sheet.append(["Name", "Title", "Profile_URL", "Email"])

    for record in records:
        sheet.append([record.name, record.title, record.profile_url, record.email])

    workbook.save(path)
    logger.info("Exported %s faculty records to %s.", len(records), path)


def title_pending_output_path(output_path: str | Path) -> Path:
    main_path = Path(output_path)
    return main_path.parent / "pending_title" / f"{main_path.stem}_title_pending.xlsx"


def export_title_pending_to_excel(
    records: list[TitlePendingRecord],
    output_path: str | Path,
) -> Path | None:
    path = title_pending_output_path(output_path)
    unique_records = remove_duplicate_title_pending_records(records)
    if not unique_records:
        if path.exists():
            path.unlink()
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Title Pending"
    sheet.append(
        [
            "Name",
            "Directory_Title",
            "Profile_URL",
            "Email",
            "Section",
            "Source_URL",
            "Pending_Reason",
            "Next_Action",
            "Status",
        ]
    )
    for record in unique_records:
        sheet.append(
            [
                record.name,
                record.directory_title,
                record.profile_url,
                record.email,
                record.section,
                record.source_url,
                record.pending_reason,
                record.next_action,
                record.status,
            ]
        )
    workbook.save(path)
    return path
