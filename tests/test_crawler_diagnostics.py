import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import faculty_crawler as faculty_crawler_module
from crawler.faculty_crawler import EmptyFetchError, FacultyCrawler, TransientLoadError
from crawler.models import DynamicTrace, TaskStatus
from crawler.parsers import FacultyRecord
from crawler.session_store import SessionProtectionError
from crawler.title_classifier import ClassificationResult, StaffClassification, TitleClassifier
from crawler.title_pipeline import ProcessedTitle, TitlePipeline
from crawler.translation import TranslationResult, TranslationStatus
from crawler.translation_settings import TranslationSettings


class CrawlerDiagnosticsTests(unittest.TestCase):
    def test_translation_settings_build_the_default_title_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = TranslationSettings(
                endpoint="http://localhost:5500",
                cache_path=str(Path(directory) / "translations.sqlite3"),
                connect_timeout=3.0,
                response_timeout=12.0,
                retries=2,
            )

            crawler = FacultyCrawler(translation_settings=settings)

            translator = crawler.title_pipeline.translator
            self.assertEqual(translator.endpoint, "http://localhost:5500")
            self.assertEqual(translator.cache.path, Path(directory) / "translations.sqlite3")
            self.assertEqual(translator.connect_timeout, 3.0)
            self.assertEqual(translator.response_timeout, 12.0)
            self.assertEqual(translator.retries, 2)

    def test_explicit_title_pipeline_takes_precedence_over_translation_settings(self):
        pipeline = object()
        crawler = FacultyCrawler(
            title_pipeline=pipeline,
            translation_settings=TranslationSettings(),
        )

        self.assertIs(crawler.title_pipeline, pipeline)

    def test_classification_summary_counts_unique_dynamic_records(self):
        html = """
        <main>
          <article class="person-card">
            <h2><a href="/people/ada">Ada Lovelace</a></h2>
            <p>Professor</p>
          </article>
        </main>
        """
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (200, html),
            dynamic_collector=lambda _url, _html: ( [html], []),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(crawler.classification_summary, {"include": 1})
        self.assertEqual(crawler.last_diagnostics["Title classification summary"], {"include": 1})
        self.assertEqual(crawler.last_diagnostics["Title review records"], 0)
        self.assertEqual(crawler.last_diagnostics["Title excluded records"], 0)
        self.assertEqual(crawler.review_records, [])
        self.assertEqual(crawler.excluded_records, [])

    def test_export_facades_write_only_their_diagnostic_records(self):
        crawler = FacultyCrawler()
        review = FacultyRecord("Review Person", "Unknown", "https://example.edu/review")
        excluded = FacultyRecord("Excluded Person", "Emeritus", "https://example.edu/excluded")
        crawler.review_records = [review]
        crawler.excluded_records = [excluded]

        with tempfile.TemporaryDirectory() as directory:
            review_path = crawler.export_review_records(Path(directory) / "review.csv")
            excluded_path = crawler.export_excluded_records(Path(directory) / "excluded.csv")

            self.assertIn("Review Person", review_path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("Excluded Person", review_path.read_text(encoding="utf-8-sig"))
            self.assertIn("Excluded Person", excluded_path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("Review Person", excluded_path.read_text(encoding="utf-8-sig"))

    def test_post_parse_title_pipeline_keeps_include_and_audits_exclude_and_review(self):
        class FakeTitlePipeline:
            def process(self, title_original, *, language_hint=""):
                outcomes = {
                    "Professor": StaffClassification.INCLUDE,
                    "Chair": StaffClassification.EXCLUDE,
                    "Dean": StaffClassification.REVIEW,
                }
                classification = ClassificationResult(classification=outcomes[title_original])
                return ProcessedTitle(
                    title_original=title_original,
                    title_translated="Associate Professor" if title_original == "Dean" else "",
                    title_language="ar" if title_original == "Dean" else "",
                    classification=classification,
                    translation_status=TranslationStatus.SERVICE_UNAVAILABLE.value if title_original == "Dean" else TranslationStatus.NOT_NEEDED.value,
                    translation_engine="libretranslate" if title_original == "Dean" else "",
                )

        crawler = FacultyCrawler(title_pipeline=FakeTitlePipeline())
        html = """
        <main><h2>Academic Staff</h2>
          <div class="person"><a href="/people/ada">Ada Lovelace</a><p>Professor</p></div>
          <div class="person"><a href="/people/bob">Bob Smith</a><p>Chair</p></div>
          <div class="person"><a href="/people/cora">Cora Jones</a><p>Dean</p></div>
        </main>
        """

        records = crawler._parse_fetched_html("https://example.edu/people", html, 200)

        self.assertEqual([record.name for record in records], ["Ada Lovelace"])
        self.assertEqual([record.name for record in crawler.excluded_records], ["Bob Smith"])
        self.assertEqual([record.name for record in crawler.review_records], ["Cora Jones"])
        self.assertEqual(crawler.review_records[0].title_translated, "Associate Professor")
        self.assertEqual(crawler.review_records[0].translation_status, "service_unavailable")

    def test_translation_failure_moves_unknown_non_english_title_to_review(self):
        class OfflineTranslator:
            def translate(self, title, source_language="auto"):
                return TranslationResult(status=TranslationStatus.SERVICE_UNAVAILABLE)

        crawler = FacultyCrawler(
            title_pipeline=TitlePipeline(TitleClassifier(), OfflineTranslator())
        )
        html = """
        <main><h2>Academic Staff</h2>
          <div class="person">
            <a href="/people/cora">Cora Jones</a>
            <p>职位未知</p>
          </div>
        </main>
        """

        records = crawler._parse_fetched_html("https://example.edu/people", html, 200)

        self.assertEqual(records, [])
        self.assertEqual([record.name for record in crawler.review_records], ["Cora Jones"])
        self.assertEqual(crawler.review_records[0].title, "职位未知")
        self.assertEqual(crawler.review_records[0].translation_status, "service_unavailable")

    def test_page_language_hint_translates_unknown_latin_script_title(self):
        class ItalianTranslator:
            def __init__(self):
                self.calls = []

            def translate(self, title, source_language="auto"):
                self.calls.append((title, source_language))
                return TranslationResult(
                    status=TranslationStatus.SUCCESS,
                    translated_text="Research Fellow",
                    detected_language="it",
                )

        translator = ItalianTranslator()
        crawler = FacultyCrawler(
            title_pipeline=TitlePipeline(TitleClassifier(), translator)
        )
        html = """
        <html lang="it-IT"><main><h2>Academic Staff</h2>
          <div class="person">
            <a href="/people/giulia">Giulia Rossi</a>
            <span class="job-role">Cultore della materia</span>
          </div>
        </main></html>
        """

        records = crawler._parse_fetched_html("https://example.edu/people", html, 200)

        self.assertEqual([record.name for record in records], ["Giulia Rossi"])
        self.assertEqual(records[0].title_translated, "Research Fellow")
        self.assertEqual(records[0].title_language, "it")
        self.assertEqual(translator.calls, [("Cultore della materia", "it")])

    def test_crawl_loads_strict_session_state_into_matching_context(self):
        calls: list[tuple[str, object]] = []

        class Store:
            def load(self, hostname):
                calls.append(("load", hostname))
                return b'{"cookies":[],"origins":[]}'

        crawler, context_options = self._session_crawler(Store())
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://fa\u00df.de/faculty")

        self.assertEqual(calls, [("load", "xn--fa-hia.de")])
        self.assertEqual(
            context_options,
            [{"storage_state": {"cookies": [], "origins": []}}],
        )

    def test_crawl_never_reuses_session_across_hostnames(self):
        loaded: list[str] = []

        class Store:
            def load(self, hostname):
                loaded.append(hostname)
                return (
                    b'{"cookies":[{"name":"one","value":"1","domain":"one.edu","path":"/"}]}'
                    if hostname == "one.edu"
                    else b'{"cookies":[{"name":"two","value":"2","domain":"two.edu","path":"/"}]}'
                )

        crawler, context_options = self._session_crawler(Store())
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://one.edu/faculty")
            crawler.crawl("https://two.edu/faculty")

        self.assertEqual(loaded, ["one.edu", "two.edu"])
        self.assertEqual(
            [options["storage_state"]["cookies"][0]["name"] for options in context_options],
            ["one", "two"],
        )

    def test_context_state_filters_parent_sibling_and_sso_hosts(self):
        state = b"""{
          "cookies": [
            {"name":"exact","value":"1","domain":"example.edu","path":"/"},
            {"name":"parent","value":"2","domain":".example.edu","path":"/"},
            {"name":"sibling","value":"3","domain":"other.example.edu","path":"/"}
          ],
          "origins": [
            {"origin":"https://example.edu","localStorage":[]},
            {"origin":"https://login.example.edu","localStorage":[]},
            {"origin":"https://sso.edu","localStorage":[]}
          ]
        }"""

        class Store:
            def load(self, hostname):
                return state

        crawler, context_options = self._session_crawler(Store())
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://example.edu/faculty")

        scoped = context_options[0]["storage_state"]
        self.assertEqual([cookie["name"] for cookie in scoped["cookies"]], ["exact"])
        self.assertEqual(
            [origin["origin"] for origin in scoped["origins"]],
            ["https://example.edu"],
        )

    def test_corrupt_session_is_cleared_without_exposing_payload(self):
        cleared: list[str] = []

        class Store:
            def load(self, hostname):
                return b"not-json-private-payload"

            def clear_site(self, hostname):
                cleared.append(hostname)

        crawler, context_options = self._session_crawler(Store())
        with (
            patch.object(crawler, "_crawl_pages", return_value=[]),
            self.assertLogs("crawler.faculty_crawler", level="WARNING") as captured,
        ):
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(context_options, [{}])
        self.assertEqual(cleared, ["example.edu"])
        self.assertEqual(crawler.last_diagnostics["Session state"], "session_state_invalid")
        self.assertNotIn("private-payload", "\n".join(captured.output))

    def test_structurally_invalid_session_is_not_passed_to_playwright(self):
        cleared: list[str] = []

        class Store:
            def load(self, hostname):
                return b'{"cookies":["invalid-cookie"]}'

            def clear_site(self, hostname):
                cleared.append(hostname)

        crawler, context_options = self._session_crawler(Store())
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(context_options, [{}])
        self.assertEqual(cleared, ["example.edu"])

    def test_temporary_session_error_continues_without_state_or_cleanup(self):
        class Store:
            def load(self, hostname):
                raise SessionProtectionError("temporary protected bytes")

            def clear_site(self, hostname):
                self.cleared = True

        store = Store()
        crawler, context_options = self._session_crawler(store)
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(context_options, [{}])
        self.assertFalse(hasattr(store, "cleared"))
        self.assertEqual(crawler.last_diagnostics["Session state"], "session_load_unavailable")

    def test_absent_or_expired_session_has_fixed_diagnostic(self):
        class Store:
            def load(self, hostname):
                return None

        crawler, context_options = self._session_crawler(Store())
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(context_options, [{}])
        self.assertEqual(crawler.last_diagnostics["Session state"], "session_state_absent")

    def test_ipv6_context_skips_dns_session_store(self):
        class Store:
            def load(self, hostname):
                self.loaded = hostname

        store = Store()
        crawler, context_options = self._session_crawler(store)
        with patch.object(crawler, "_crawl_pages", return_value=[]):
            crawler.crawl("https://[2001:db8::1]/faculty")

        self.assertFalse(hasattr(store, "loaded"))
        self.assertEqual(context_options, [{}])
        self.assertEqual(crawler.last_diagnostics["Session state"], "ipv6_session_skipped")

    def test_context_creation_failure_still_closes_browser_with_fixed_error(self):
        closed: list[str] = []
        crawler = FacultyCrawler(
            playwright_factory=self._failing_browser_factory(
                context_error=RuntimeError("private state content"),
                browser_closed=lambda: closed.append("browser"),
            )
        )

        with self.assertRaises(RuntimeError) as captured:
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(closed, ["browser"])
        self.assertNotIn("private state content", str(captured.exception))

    def test_context_close_failure_still_attempts_browser_close(self):
        closed: list[str] = []

        def close_context():
            closed.append("context")
            raise RuntimeError("private context content")

        crawler = FacultyCrawler(
            playwright_factory=self._failing_browser_factory(
                context_closed=close_context,
                browser_closed=lambda: closed.append("browser"),
            )
        )
        with (
            patch.object(crawler, "_crawl_pages", return_value=[]),
            self.assertRaises(RuntimeError) as captured,
        ):
            crawler.crawl("https://example.edu/faculty")

        self.assertEqual(closed, ["context", "browser"])
        self.assertNotIn("private context content", str(captured.exception))

    @staticmethod
    def _session_crawler(store):
        context_options: list[dict[str, object]] = []

        class Page:
            def set_default_timeout(self, _timeout):
                pass

        class Context:
            def new_page(self):
                return Page()

            def close(self):
                pass

        class Browser:
            def new_context(self, **options):
                context_options.append(options)
                return Context()

            def close(self):
                pass

        class Chromium:
            def launch(self, **_options):
                return Browser()

        class Playwright:
            chromium = Chromium()

        class Manager:
            def __enter__(self):
                return Playwright()

            def __exit__(self, *_args):
                pass

        return (
            FacultyCrawler(session_store=store, playwright_factory=lambda: Manager()),
            context_options,
        )

    @staticmethod
    def _failing_browser_factory(
        *,
        context_error=None,
        context_closed=None,
        browser_closed=None,
    ):
        class Page:
            def set_default_timeout(self, _timeout):
                pass

        class Context:
            def new_page(self):
                return Page()

            def close(self):
                if context_closed:
                    context_closed()

        class Browser:
            def new_context(self, **_options):
                if context_error:
                    raise context_error
                return Context()

            def close(self):
                if browser_closed:
                    browser_closed()

        class Chromium:
            def launch(self, **_options):
                return Browser()

        class Playwright:
            chromium = Chromium()

        class Manager:
            def __enter__(self):
                return Playwright()

            def __exit__(self, *_args):
                pass

        return lambda: Manager()

    def test_successful_network_idle_capture_returns_current_html(self):
        html = self._directory_page(10)

        class Page:
            def wait_for_load_state(self, *_args, **_kwargs):
                return None

            def content(self):
                return html

        result = faculty_crawler_module._settle_page_content(
            Page(),
            "https://example.edu/faculty",
            timeout_ms=1000,
            timeout_error=TimeoutError,
        )

        self.assertEqual(result, html)

    def test_transient_load_exception_retries_then_succeeds(self):
        attempts = iter(
            [
                TimeoutError("navigation timeout"),
                (200, self._directory_page(10)),
            ]
        )
        sleeps: list[float] = []
        crawler = FacultyCrawler()

        def load(_url: str):
            result = next(attempts)
            if isinstance(result, Exception):
                raise result
            return result

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=load,
            sleep=sleeps.append,
        )

        self.assertEqual(len(records), 10)
        self.assertEqual(sleeps, [1.0])
        self.assertEqual(
            crawler.last_diagnostics["Retry traces"],
            [{"status_code": None, "attempt": 0, "delay": 1.0, "reason": "bounded_retry"}],
        )

    def test_transient_load_exception_exhausts_bounded_retries(self):
        calls: list[str] = []
        sleeps: list[float] = []
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda url: (calls.append(url), (_ for _ in ()).throw(TransientLoadError("offline")))[1],
            sleep=sleeps.append,
        )

        self.assertEqual(records, [])
        self.assertEqual(len(calls), 4)
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])
        self.assertEqual(crawler.last_diagnostics["Retry attempts"], 3)

    def test_programming_error_is_not_retried(self):
        crawler = FacultyCrawler()

        with self.assertRaisesRegex(ValueError, "broken fake"):
            crawler._crawl_pages(
                "https://example.edu/faculty",
                load_attempt=lambda _url: (_ for _ in ()).throw(ValueError("broken fake")),
                sleep=lambda _delay: self.fail("must not sleep"),
            )

    def test_exhausted_http_error_does_not_run_dynamic_actions(self):
        crawler = FacultyCrawler()
        error_html = "<html><body>Too many requests " + ("x" * 200) + "</body></html>"

        crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (429, error_html),
            sleep=lambda _delay: None,
            dynamic_action=lambda *_args: self.fail("must not act on an HTTP error"),
            dynamic_collector=lambda *_args: self.fail("must not collect an HTTP error"),
        )

    def test_delayed_shell_waits_and_reclassifies_without_retry_trace(self):
        attempts = iter(
            [
                (200, "<html><body><div id='app'></div></body></html>"),
                (200, self._directory_page(10)),
            ]
        )
        waits: list[float] = []
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: next(attempts),
            render_wait=waits.append,
        )

        self.assertEqual(len(records), 10)
        self.assertEqual(waits, [0.25])
        self.assertEqual(crawler.last_diagnostics["Retry attempts"], 0)
        self.assertEqual(
            [item["kind"] for item in crawler.last_diagnostics["Page assessment"]],
            ["delayed_shell", "directory"],
        )

    def test_empty_visible_text_does_not_use_hidden_challenge_text(self):
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: {
                "status": 403,
                "html": "<html><body><div hidden>Verify you are human</div></body></html>",
                "title": "",
                "text": "",
                "text_available": True,
            },
        )

        self.assertEqual(records, [])
        self.assertNotEqual(crawler._outcome_from_records(records).status, TaskStatus.VERIFICATION_REQUIRED)

    def test_ordinary_next_is_not_also_clicked_by_dynamic_navigation(self):
        crawler = FacultyCrawler()
        first = self._directory_page(10) + '<a rel="next" href="?page=2">Next</a>'
        expanded = first + self._person_page("Extra Professor", "extra")
        second = self._person_page("Last Professor", "last")
        loader_calls: list[str] = []
        action_calls: list[tuple[str, str]] = []
        collector_inputs: list[tuple[str, str]] = []

        def loader(page_url: str):
            loader_calls.append(page_url)
            return 200, first if "page=2" not in page_url else second

        def action(action: str, page_url: str, _profiles: set[str]):
            action_calls.append((action, page_url))
            return (
                expanded
                if action == "largest_page_size" and "page=2" not in page_url
                else None
            )

        def collector(page_url: str, html: str):
            collector_inputs.append((page_url, html))
            return [], [DynamicTrace("scroll", 0, (), "control_exhausted")]

        crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=loader,
            dynamic_action=action,
            dynamic_collector=collector,
        )

        self.assertEqual(loader_calls, ["https://example.edu/faculty", "https://example.edu/faculty?page=2"])
        self.assertNotIn(("next", "https://example.edu/faculty"), action_calls)
        self.assertEqual(collector_inputs[0], ("https://example.edu/faculty", expanded))
        self.assertEqual(
            collector_inputs[1],
            ("https://example.edu/faculty?page=2", second),
        )

    def test_javascript_next_reuses_live_page_without_loader_request(self):
        crawler = FacultyCrawler()
        first = self._directory_page(10)
        second = self._person_page("JavaScript Page", "js-page")
        loader_calls: list[str] = []
        collector_html: list[str] = []
        next_results = iter([second, None])

        def action(action: str, _page_url: str, _profiles: set[str]):
            if action == "next":
                return next(next_results)
            return None

        crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda page_url: (loader_calls.append(page_url), (200, first))[1],
            dynamic_action=action,
            dynamic_collector=lambda _url, html: (collector_html.append(html), ([], []))[1],
        )

        self.assertEqual(loader_calls, ["https://example.edu/faculty"])
        self.assertEqual(collector_html, [first, second])

    def test_dynamic_verification_stops_before_ordinary_next_load(self):
        crawler = FacultyCrawler()
        initial = self._person_page("Ada Lovelace", "ada") + '<a rel="next" href="?page=2">Next</a>'
        accepted = self._person_page("Grace Hopper", "grace")
        loader_calls: list[str] = []
        trace = DynamicTrace("load_more", 1, (1,), "verification_required")

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda page_url: (loader_calls.append(page_url), (200, initial))[1],
            dynamic_collector=lambda _url, _html: ([accepted], [trace]),
        )

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(loader_calls, ["https://example.edu/faculty"])
        self.assertEqual(crawler._outcome_from_records(records).status, TaskStatus.VERIFICATION_REQUIRED)

    def test_javascript_next_challenge_is_reclassified_and_stops(self):
        crawler = FacultyCrawler()
        initial = self._directory_page(10)
        challenge = "<html><title>Just a moment</title><body>Verify you are human</body></html>"
        actions: list[str] = []
        collector_calls: list[str] = []

        def action(action_name: str, _url: str, _profiles: set[str]):
            actions.append(action_name)
            if action_name == "next":
                return challenge
            return None

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (200, initial),
            dynamic_action=action,
            dynamic_collector=lambda _url, html: (
                collector_calls.append(html),
                ([], []),
            )[1],
        )
        outcome = crawler._outcome_from_records(records)

        self.assertEqual(len(records), 10)
        self.assertEqual(outcome.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(actions, ["largest_page_size", "next"])
        self.assertEqual(collector_calls, [initial])
        self.assertEqual(outcome.diagnostics["Page assessment"][-1]["kind"], "human_verification")

    def test_javascript_next_retryable_error_stops_with_diagnostics(self):
        for status, expected_kind in ((429, "rate_limited"), (503, "temporary_failure")):
            with self.subTest(status=status):
                crawler = FacultyCrawler()
                initial = self._directory_page(10)

                def action(action_name: str, _url: str, _profiles: set[str]):
                    if action_name == "next":
                        return {
                            "status": status,
                            "html": "<html><body>Temporarily unavailable</body></html>",
                            "title": "Unavailable",
                            "text": "Temporarily unavailable",
                        }
                    return None

                records = crawler._crawl_pages(
                    "https://example.edu/faculty",
                    load_attempt=lambda _url: (200, initial),
                    dynamic_action=action,
                )
                outcome = crawler._outcome_from_records(records)

                self.assertEqual(len(records), 10)
                self.assertEqual(outcome.status, TaskStatus.REVIEW_RECOMMENDED)
                self.assertEqual(outcome.diagnostics["Failure stage"], "dynamic_next")
                self.assertEqual(outcome.diagnostics["Page assessment"][-1]["kind"], expected_kind)

    def test_dynamic_snapshots_use_collectors_final_url_for_relative_profiles(self):
        crawler = FacultyCrawler()
        initial = self._person_page("Ada Lovelace", "ada")
        grace = self._person_page("Grace Hopper", "grace").replace('href="/people/', 'href="people/')
        alan = self._person_page("Alan Turing", "alan").replace('href="/people/', 'href="people/')
        final_html = grace + alan

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (200, initial),
            dynamic_collector=lambda _url, _html: {
                "snapshots": [grace],
                "traces": [],
                "final_html": final_html,
                "final_url": "https://example.edu/department/",
            },
        )

        self.assertEqual(
            [(record.name, record.profile_url) for record in records],
            [
                ("Ada Lovelace", "https://example.edu/people/ada"),
                ("Grace Hopper", "https://example.edu/department/people/grace"),
                ("Alan Turing", "https://example.edu/department/people/alan"),
            ],
        )

    def test_identical_final_html_is_reparsed_when_collector_base_url_changes(self):
        crawler = FacultyCrawler()
        html = self._person_page("Ada Lovelace", "ada").replace(
            'href="/people/',
            'href="people/',
        )

        records = crawler._crawl_pages(
            "https://example.edu/faculty/",
            load_attempt=lambda _url: (200, html),
            dynamic_collector=lambda _url, _html: {
                "snapshots": [],
                "traces": [],
                "final_html": html,
                "final_url": "https://example.edu/department/",
            },
        )

        self.assertEqual(
            [record.profile_url for record in records],
            [
                "https://example.edu/faculty/people/ada",
                "https://example.edu/department/people/ada",
            ],
        )

    def test_rate_limit_retries_then_succeeds_without_real_sleep(self):
        attempts = iter(
            [
                (429, "<html><title>Busy</title><body>Too many requests</body></html>"),
                (
                    200,
                    "".join(
                        self._person_page(f"Professor {index}", f"professor-{index}")
                        for index in range(10)
                    ),
                ),
            ]
        )
        sleeps: list[float] = []
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: next(attempts),
            sleep=sleeps.append,
        )
        outcome = crawler._outcome_from_records(records)

        self.assertEqual(outcome.status, TaskStatus.SUCCEEDED)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(outcome.diagnostics["Retry attempts"], 1)
        self.assertEqual(
            outcome.diagnostics["Retry traces"],
            [{"status_code": 429, "attempt": 0, "delay": 1.0, "reason": "bounded_retry"}],
        )

    def test_challenge_returns_verification_required_without_retry(self):
        crawler = FacultyCrawler()

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (
                403,
                "<html><title>Just a moment</title><body>Verify you are human</body></html>",
            ),
            sleep=lambda _delay: self.fail("must not sleep"),
        )
        outcome = crawler._outcome_from_records(records)

        self.assertEqual(outcome.status, TaskStatus.VERIFICATION_REQUIRED)
        self.assertEqual(outcome.diagnostics["Retry attempts"], 0)

    def test_dynamic_snapshots_are_all_parsed_and_deduplicated(self):
        crawler = FacultyCrawler()
        initial = self._person_page("Ada Lovelace", "ada")
        snapshots = [
            initial,
            self._person_page("Grace Hopper", "grace"),
        ]

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (200, initial),
            dynamic_collector=lambda _url, _html: (snapshots, []),
        )

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper"])

    def test_dynamic_trace_is_written_to_diagnostics(self):
        crawler = FacultyCrawler()
        initial = self._person_page("Ada Lovelace", "ada")
        trace = DynamicTrace("load_more", 2, (20, 8), "control_exhausted")

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda _url: (200, initial),
            dynamic_collector=lambda _url, _html: ([], [trace]),
        )
        outcome = crawler._outcome_from_records(records)

        self.assertEqual(outcome.diagnostics["Dynamic traces"][0]["additions"], [20, 8])
        self.assertEqual(outcome.diagnostics["Dynamic stop reason"], "control_exhausted")

    def test_consent_is_checked_only_once_for_a_paginated_directory(self):
        crawler = FacultyCrawler()
        calls: list[str] = []
        pages = {
            "https://example.edu/faculty": self._person_page("Ada Lovelace", "ada")
            + '<a rel="next" href="?page=2">Next</a>',
            "https://example.edu/faculty?page=2": self._person_page("Grace Hopper", "grace"),
        }

        crawler._crawl_pages(
            "https://example.edu/faculty",
            load_attempt=lambda page_url: (200, pages[page_url]),
            consent_action=lambda: calls.append("checked"),
        )

        self.assertEqual(calls, ["checked"])

    def test_crawl_outcome_wraps_records_and_diagnostics(self):
        crawler = FacultyCrawler()
        crawler._crawl_pages = lambda url, load_page, load_dynamic_pages=None: [
            FacultyRecord("Ada", "Professor", "https://example.edu/ada")
        ]
        crawler.last_diagnostics = {"Failure stage": ""}

        outcome = crawler._outcome_from_records(
            crawler._crawl_pages("https://example.edu", lambda url: ("", 200))
        )

        self.assertEqual(outcome.status, TaskStatus.SUCCEEDED)
        self.assertEqual(outcome.records[0].name, "Ada")

    def test_waits_for_directory_candidates_after_network_idle_timeout(self):
        shell_html = "<html><body><div id='app'></div></body></html>"
        rendered_html = self._person_page("Ada Lovelace", "ada-lovelace")

        class DelayedDirectoryPage:
            def __init__(self):
                self.snapshots = iter([shell_html, rendered_html])
                self.waits: list[int] = []

            def wait_for_timeout(self, milliseconds: int) -> None:
                self.waits.append(milliseconds)

            def content(self) -> str:
                return next(self.snapshots)

        page = DelayedDirectoryPage()

        html = faculty_crawler_module._wait_for_rendered_directory_content(
            page,
            "https://example.edu/department/people",
            shell_html,
            timeout_ms=1000,
        )

        self.assertEqual(html, rendered_html)
        self.assertEqual(page.waits, [250, 250])

    def test_http_error_status_is_fetch_stage_failure(self):
        crawler = FacultyCrawler()

        records = crawler._parse_fetched_html(
            url="https://www.imperial.ac.uk/computing/people/",
            html="<html><body><h1>Forbidden</h1></body></html>",
            fetch_status=403,
        )

        self.assertEqual(records, [])
        self.assertEqual(crawler.last_diagnostics["Failure stage"], "fetch")
        self.assertEqual(crawler.last_diagnostics["Failure reason"], "HTTP 403 Forbidden")
        self.assertEqual(crawler.last_diagnostics["Detected page type"], "unknown")
        self.assertEqual(crawler.last_diagnostics["Number of candidate records"], 0)

    def test_empty_html_raises_fetch_stage_error(self):
        crawler = FacultyCrawler()

        with self.assertRaisesRegex(EmptyFetchError, "Empty response after fetch"):
            crawler._parse_fetched_html(
                url="https://www.imperial.ac.uk/computing/people/",
                html="",
                fetch_status=202,
            )

        self.assertEqual(crawler.last_diagnostics["Failure reason"], "Empty or too short HTML response")

    def test_short_html_is_fetch_stage_failure(self):
        crawler = FacultyCrawler()

        records = crawler._parse_fetched_html(
            url="https://example.edu/faculty",
            html="<html><body>OK</body></html>",
            fetch_status=200,
        )

        self.assertEqual(records, [])
        self.assertEqual(crawler.last_diagnostics["Failure stage"], "fetch")
        self.assertEqual(crawler.last_diagnostics["Failure reason"], "Empty or too short HTML response")
        self.assertEqual(crawler.last_diagnostics["Detected page type"], "unknown")

    def test_non_empty_directory_html_with_one_record_reports_low_coverage(self):
        crawler = FacultyCrawler()
        html = """
        <main>
          <article class="person-card">
            <h2><a href="/people/ada-lovelace">Ada Lovelace</a></h2>
            <p>Professor of Computing</p>
          </article>
        </main>
        """

        records = crawler._parse_fetched_html(
            url="https://example.edu/faculty",
            html=html,
            fetch_status=200,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(crawler.last_diagnostics["URL"], "https://example.edu/faculty")
        self.assertEqual(crawler.last_diagnostics["Fetch status"], 200)
        self.assertGreater(crawler.last_diagnostics["HTML length"], 0)
        self.assertEqual(crawler.last_diagnostics["Detected page type"], "card")
        self.assertEqual(crawler.last_diagnostics["Number of candidate records"], 1)
        self.assertEqual(crawler.last_diagnostics["Number of parsed records"], 1)
        self.assertEqual(crawler.last_diagnostics["Failure stage"], "low_coverage_warning")

    def test_crawl_pages_follows_next_query_and_deduplicates_profiles(self):
        crawler = FacultyCrawler()
        pages = {
            "https://example.edu/docentes": """
                <main><div><h5>Arlete Moyses Rodrigues</h5><p>Docente</p><a href="/pessoas/arlete">ver perfil</a></div>
                <nav><a href="?page=1" rel="next">Next</a></nav></main>
            """,
            "https://example.edu/docentes?page=1": """
                <main><div><h5>Arlete Moyses Rodrigues</h5><p>Docente</p><a href="/pessoas/arlete">ver perfil</a></div>
                <div><h5>Maria Lygia Quartim de Moraes</h5><p>Docente</p><a href="/pessoas/maria-lygia">ver perfil</a></div></main>
            """,
        }

        records = crawler._crawl_pages("https://example.edu/docentes", lambda page_url: (pages[page_url], 200))

        self.assertEqual([record.name for record in records], ["Arlete Moyses Rodrigues", "Maria Lygia Quartim de Moraes"])
        self.assertEqual(crawler.last_diagnostics["Pagination pages visited"], 2)

    def test_parse_fetched_html_keeps_distinct_wordpress_page_ids(self):
        crawler = FacultyCrawler()
        html = """
        <main><div class="entry-content">
          <div><h3>Full-time Faculty</h3><hr></div>
          <h4><a href="/?page_id=7001">Ada Lovelace</a></h4>
          <h5>Professor</h5>
          <h5>E-mail: <a href="mailto:ada@example.edu">ada@example.edu</a></h5>
          <p><a href="/?page_id=7002">Grace Hopper</a></p>
          <h5>Associate Professor</h5>
          <h5>E-mail: <a href="mailto:grace@example.edu">grace@example.edu</a></h5>
        </div></main>
        """

        records = crawler._parse_fetched_html(
            url="https://example.edu/?page_id=6084",
            html=html,
            fetch_status=200,
        )

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(crawler.last_diagnostics["Number of candidate records"], 2)
        self.assertEqual(crawler.last_diagnostics["Number of parsed records"], 2)

    def test_dynamic_directory_prefers_largest_page_size_then_follows_next_until_no_new_profiles(self):
        initial_html = self._person_page("Ada Lovelace", "ada-lovelace")
        largest_html = initial_html + self._person_page("Grace Hopper", "grace-hopper")
        next_html = self._person_page("Alan Turing", "alan-turing")
        repeated_html = self._person_page("Alan Turing", "alan-turing")
        responses = iter([largest_html, next_html, repeated_html])
        actions: list[str] = []

        def interact(action: str, current_profile_urls: set[str]) -> str | None:
            actions.append(action)
            return next(responses)

        pages = faculty_crawler_module._collect_dynamic_result_pages(
            initial_html,
            "https://example.edu/department/people",
            interact,
        )

        self.assertEqual(pages, [largest_html, next_html])
        self.assertEqual(actions, ["largest_page_size", "next", "next"])

    def test_dynamic_directory_uses_explicit_next_when_no_page_size_control_exists(self):
        initial_html = self._person_page("Ada Lovelace", "ada-lovelace")
        next_html = self._person_page("Grace Hopper", "grace-hopper")
        responses = iter([None, next_html, None])
        actions: list[str] = []

        def interact(action: str, current_profile_urls: set[str]) -> str | None:
            actions.append(action)
            return next(responses)

        pages = faculty_crawler_module._collect_dynamic_result_pages(
            initial_html,
            "https://example.edu/department/people",
            interact,
        )

        self.assertEqual(pages, [next_html])
        self.assertEqual(actions, ["largest_page_size", "next", "next"])

    def test_crawl_pages_merges_dynamic_result_snapshots(self):
        crawler = FacultyCrawler()
        initial_html = self._person_page("Ada Lovelace", "ada-lovelace")
        dynamic_html = self._person_page("Grace Hopper", "grace-hopper")

        records = crawler._crawl_pages(
            "https://example.edu/department/people",
            lambda page_url: (initial_html, 200),
            lambda page_url, html: [dynamic_html],
        )

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(crawler.last_diagnostics["Pagination pages visited"], 2)

    def test_crawl_pages_accumulates_pending_and_complete_record_wins_by_profile_url(self):
        crawler = FacultyCrawler()
        pages = {
            "https://example.edu/faculty": """
                <main><h2>Academic Staff</h2>
                <article class="person-card"><h3><a href="/people/ada">Ada Lovelace</a></h3><p class="title">Dr.</p></article>
                <nav><a href="?page=2" rel="next">Next</a></nav></main>
            """,
            "https://example.edu/faculty?page=2": """
                <main><h2>Academic Staff</h2>
                <article class="person-card"><h3><a href="/people/ada">Ada Lovelace</a></h3><p class="title">Professor</p></article>
                <article class="person-card"><h3><a href="/people/grace?utm_source=test">Grace Hopper</a></h3></article>
                <article class="person-card"><h3><a href="/people/grace">Grace Hopper</a></h3></article></main>
            """,
        }

        records = crawler._crawl_pages(
            "https://example.edu/faculty",
            lambda page_url: (pages[page_url], 200),
        )

        self.assertEqual([(record.name, record.title) for record in records], [("Ada Lovelace", "Professor")])
        self.assertEqual(
            [(record.name, record.profile_url) for record in crawler.title_pending_records],
            [("Grace Hopper", "https://example.edu/people/grace?utm_source=test")],
        )

    @staticmethod
    def _person_page(name: str, slug: str) -> str:
        return f"""
        <main>
          <div class="person-result">
            <h4><a href="/people/{slug}">{name}</a></h4>
            <span>Professor</span>
          </div>
        </main>
        """

    @classmethod
    def _directory_page(cls, count: int) -> str:
        return "".join(
            cls._person_page(f"Professor {index}", f"professor-{index}")
            for index in range(count)
        )


if __name__ == "__main__":
    unittest.main()
