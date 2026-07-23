import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from crawler.dynamic_loader import _PlaywrightDynamicAdapter, collect_dynamic_snapshots


class FakeDynamicPage:
    def __init__(self, events):
        self.events = iter(events)
        self.actions = []

    def dynamic_step(self, action):
        self.actions.append(action)
        return next(self.events, None)


class EvaluatingPage:
    def __init__(self, values):
        self.values = iter(values)
        self.actions = []
        self.waited = None

    def evaluate(self, script, action=None):
        if isinstance(action, str):
            self.actions.append(action)
        return next(self.values)

    def content(self):
        return "<main><a href='/people/ada'>Ada Lovelace</a></main>"

    def wait_for_timeout(self, milliseconds):
        self.waited = milliseconds


class DynamicLoaderTests(unittest.TestCase):
    def test_load_more_stops_after_two_unchanged_rounds(self):
        page = FakeDynamicPage(
            [
                ("load_more", "<a href='/people/a'>A</a>"),
                ("load_more", "<a href='/people/a'>A</a>"),
                ("load_more", "<a href='/people/a'>A</a>"),
            ]
        )

        snapshots, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<main></main>",
            max_clicks=10,
            max_scrolls=0,
        )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(traces[0].rounds, 3)
        self.assertEqual(traces[0].additions, (1, 0, 0))
        self.assertEqual(traces[0].stop_reason, "two_unchanged_clicks")

    def test_scrolling_stops_after_three_unchanged_rounds(self):
        page = FakeDynamicPage(
            [
                ("window_scroll", "<a href='/people/a'>A</a>"),
                ("window_scroll", "<a href='/people/a'>A</a>"),
                ("window_scroll", "<a href='/people/a'>A</a>"),
                ("window_scroll", "<a href='/people/a'>A</a>"),
            ]
        )

        _, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<main></main>",
            max_clicks=0,
            max_scrolls=10,
        )

        self.assertEqual(traces[-1].rounds, 4)
        self.assertEqual(traces[-1].additions, (1, 0, 0, 0))
        self.assertEqual(traces[-1].stop_reason, "three_unchanged_scrolls")

    def test_virtual_list_keeps_each_changed_snapshot(self):
        page = FakeDynamicPage(
            [
                ("internal_scroll", "<a href='/people/a'>A</a>"),
                ("internal_scroll", "<a href='/people/b'>B</a>"),
                None,
            ]
        )

        snapshots, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<main></main>",
            max_clicks=0,
            max_scrolls=10,
        )

        self.assertEqual(len(snapshots), 2)
        self.assertIn("/people/a", snapshots[0])
        self.assertIn("/people/b", snapshots[1])
        self.assertEqual(traces[-1].stop_reason, "control_exhausted")

    def test_normalized_profile_urls_are_deduplicated(self):
        page = FakeDynamicPage(
            [("load_more", "<a href='/people/ada/'>Ada Lovelace</a>"), None]
        )

        snapshots, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<a href='/people/ada?utm_source=list'>Ada Lovelace</a>",
            max_clicks=2,
            max_scrolls=0,
        )

        self.assertEqual(snapshots, [])
        self.assertEqual(traces[0].additions, (0,))

    def test_explicit_round_limits_bound_both_actions(self):
        page = FakeDynamicPage(
            [
                ("load_more", "<a href='/people/a'>A</a>"),
                ("window_scroll", "<a href='/people/b'>B</a>"),
                ("window_scroll", "<a href='/people/c'>C</a>"),
                ("window_scroll", "<a href='/people/d'>D</a>"),
            ]
        )

        _, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<main></main>",
            max_clicks=1,
            max_scrolls=2,
        )

        self.assertEqual(page.actions, ["load_more", "scroll", "scroll"])
        self.assertEqual([trace.rounds for trace in traces], [1, 2])
        self.assertEqual([trace.stop_reason for trace in traces], ["round_limit", "round_limit"])

    def test_elapsed_deadline_stops_before_another_action(self):
        page = FakeDynamicPage(
            [
                ("load_more", "<a href='/people/a'>A</a>"),
                ("load_more", "<a href='/people/b'>B</a>"),
            ]
        )

        with patch("crawler.dynamic_loader.monotonic", side_effect=[0.0, 0.0, 0.051]):
            snapshots, traces = collect_dynamic_snapshots(
                page,
                "https://example.edu",
                "<main></main>",
                max_clicks=10,
                max_scrolls=10,
                timeout_ms=50,
            )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(page.actions, ["load_more"])
        self.assertEqual(traces[-1].stop_reason, "timeout")

    def test_action_that_crosses_deadline_stops_its_current_phase(self):
        class Clock:
            now = 0.0

            def __call__(self):
                return self.now

        class AdvancingPage(FakeDynamicPage):
            def dynamic_step(self, action):
                event = super().dynamic_step(action)
                clock.now = 0.051
                return event

        clock = Clock()
        page = AdvancingPage([("load_more", "<a href='/people/a'>A</a>")])

        with patch("crawler.dynamic_loader.monotonic", clock):
            snapshots, traces = collect_dynamic_snapshots(
                page,
                "https://example.edu",
                "<main></main>",
                max_clicks=1,
                max_scrolls=10,
                timeout_ms=50,
            )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(page.actions, ["load_more"])
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].stop_reason, "timeout")

    def test_none_after_deadline_reports_timeout_not_control_exhausted(self):
        class Clock:
            now = 0.0

            def __call__(self):
                return self.now

        class AdvancingPage(FakeDynamicPage):
            def dynamic_step(self, action):
                super().dynamic_step(action)
                clock.now = 0.051
                return None

        clock = Clock()
        page = AdvancingPage([None])

        with patch("crawler.dynamic_loader.monotonic", clock):
            _, traces = collect_dynamic_snapshots(
                page,
                "https://example.edu",
                "<main></main>",
                max_clicks=1,
                max_scrolls=0,
                timeout_ms=50,
            )

        self.assertEqual(traces[0].stop_reason, "timeout")

    def test_verification_event_stops_all_further_actions(self):
        page = FakeDynamicPage(
            [
                ("verification_required", "<main>Verify you are human</main>"),
                ("window_scroll", "<a href='/people/a'>A</a>"),
            ]
        )

        snapshots, traces = collect_dynamic_snapshots(
            page,
            "https://example.edu",
            "<main></main>",
            max_clicks=10,
            max_scrolls=10,
        )

        self.assertEqual(snapshots, [])
        self.assertEqual(page.actions, ["load_more"])
        self.assertEqual(traces[-1].stop_reason, "verification_required")

    def test_adapter_reports_load_more_action(self):
        page = EvaluatingPage(
            [
                {"acted": True, "kind": "load_more"},
                {"settled": True, "challenge": False},
            ]
        )
        adapter = _PlaywrightDynamicAdapter(page, timeout_ms=1000)

        event = adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "load_more")
        self.assertEqual(page.actions, ["load_more"])
        self.assertIsNone(page.waited)

    def test_adapter_reports_internal_scroll_action(self):
        page = EvaluatingPage(
            [
                {"acted": True, "kind": "internal_scroll"},
                {"settled": True, "challenge": False},
            ]
        )
        adapter = _PlaywrightDynamicAdapter(page, timeout_ms=1000)

        event = adapter.dynamic_step("scroll")

        self.assertEqual(event[0], "internal_scroll")

    def test_adapter_action_time_is_not_added_back_to_global_deadline(self):
        class Clock:
            now = 0.0

            def __call__(self):
                return self.now

        class SlowEvaluatingPage:
            def __init__(self):
                self.waits = []

            def evaluate(self, script, action=None):
                if isinstance(action, str):
                    clock.now = 0.040
                    return {"acted": True, "kind": "load_more"}
                return {"settled": False, "challenge": False}

            def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)
                clock.now += milliseconds / 1000

            def content(self):
                return "<main></main>"

        clock = Clock()
        page = SlowEvaluatingPage()
        adapter = _PlaywrightDynamicAdapter(page, timeout_ms=1000)

        with patch("crawler.dynamic_loader.monotonic", clock):
            _, traces = collect_dynamic_snapshots(
                adapter,
                "https://example.edu",
                "<main></main>",
                max_clicks=1,
                max_scrolls=0,
                timeout_ms=50,
            )

        self.assertLessEqual(sum(page.waits), 11)
        self.assertEqual(traces[0].stop_reason, "timeout")


class PlaywrightDynamicAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 800, "height": 300})
        self.adapter = _PlaywrightDynamicAdapter(self.page, timeout_ms=0)

    def tearDown(self):
        self.page.close()

    def test_clicks_exact_accessible_label_inside_people_scope(self):
        self.page.set_content(
            "<section>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button aria-label='Load more' onclick='window.clicked = true'>News</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "load_more")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_aria_labelledby_precedes_aria_label_and_visible_text(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<span id='unsafe'>View events</span>"
            "<button aria-labelledby='unsafe' aria-label='Load more' "
            "onclick='window.clicked = true'>Load more</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_aria_labelledby_uses_referenced_role_img_accessible_name(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<span id='unsafe' role='img' aria-label='View events'></span>"
            "<button aria-labelledby='unsafe' onclick='window.clicked = true'>"
            "Load more</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_aria_labelledby_concatenates_referenced_text_in_id_order(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<span id='second'>more</span><span id='first'>Load</span>"
            "<button aria-labelledby='first second' aria-label='View events' "
            "onclick='window.clicked = true'>View events</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "load_more")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_title_is_used_as_accessible_name_fallback(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button title='Load more' onclick='window.clicked = true'></button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "load_more")
        self.assertTrue(self.page.evaluate("window.clicked"))

    def test_does_not_climb_from_events_to_shared_main_people_links(self):
        self.page.set_content(
            "<main>"
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "</section>"
            "<section class='events'>"
            "<button onclick='window.eventsClicked = true'>Load more</button>"
            "</section>"
            "</main>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.eventsClicked"))

    def test_clicks_list_local_control_without_using_shared_main(self):
        self.page.set_content(
            "<main>"
            "<section class='events'>"
            "<button onclick='window.eventsClicked = true'>Load more</button>"
            "</section>"
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick='window.peopleClicked = true'>Load more</button>"
            "</section>"
            "</main>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "load_more")
        self.assertIsNone(self.page.evaluate("window.eventsClicked"))
        self.assertTrue(self.page.evaluate("window.peopleClicked"))

    def test_does_not_click_unscoped_or_generic_more_controls(self):
        self.page.set_content(
            "<main>"
            "<section class='people'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick='window.genericClicked = true'>More</button>"
            "</section>"
            "<section class='news'>"
            "<button onclick='window.newsClicked = true'>Load more</button>"
            "</section>"
            "<section class='course-list'>"
            "<button onclick='window.courseClicked = true'>Show more</button>"
            "</section>"
            "<section class='privacy'>"
            "<button onclick='window.privacyClicked = true'>Load more</button>"
            "</section>"
            "</main>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.genericClicked"))
        self.assertIsNone(self.page.evaluate("window.newsClicked"))
        self.assertIsNone(self.page.evaluate("window.courseClicked"))
        self.assertIsNone(self.page.evaluate("window.privacyClicked"))

    def test_does_not_click_disabled_or_aria_disabled_controls(self):
        self.page.set_content(
            "<section>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button disabled onclick='window.nativeClicked = true'>Load more</button>"
            "<div role='button' aria-disabled='true' aria-label='Show more' "
            "onclick='window.ariaClicked = true'></div>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.nativeClicked"))
        self.assertIsNone(self.page.evaluate("window.ariaClicked"))

    def test_disabled_fieldset_control_returns_without_using_wait_budget(self):
        class RecordingPage:
            def __init__(self, page):
                self.page = page
                self.waits = []

            def __getattr__(self, name):
                return getattr(self.page, name)

            def wait_for_timeout(self, milliseconds):
                self.waits.append(milliseconds)
                self.page.wait_for_timeout(milliseconds)

        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<fieldset disabled><button onclick='window.clicked = true'>"
            "Load more</button></fieldset>"
            "</section>"
        )
        recording_page = RecordingPage(self.page)
        adapter = _PlaywrightDynamicAdapter(recording_page, timeout_ms=1000)

        event = adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertEqual(recording_page.waits, [])
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_cross_origin_people_paths_cannot_establish_trusted_scope(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='https://untrusted.example/people/ada'>Ada Lovelace</a>"
            "<a href='https://untrusted.example/people/grace'>Grace Hopper</a>"
            "<button onclick='window.clicked = true'>Load more</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_empty_identity_queries_cannot_establish_trusted_scope(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/profile?personid='>Ada Lovelace</a>"
            "<a href='/directory?staffid='>Grace Hopper</a>"
            "<button onclick='window.clicked = true'>Load more</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_organizational_people_paths_cannot_establish_trusted_scope(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/departments/law/people/ada'>Law department</a>"
            "<a href='/schools/business/people/grace'>Business school</a>"
            "<button onclick='window.clicked = true'>Load more</button>"
            "</section>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertIsNone(event)
        self.assertIsNone(self.page.evaluate("window.clicked"))

    def test_prefers_scrollable_people_list_ancestor(self):
        self.page.set_content(
            "<div id='people' style='height: 100px; overflow-y: auto'>"
            "<div style='height: 700px'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "</div></div>"
            "<div style='height: 1000px'></div>"
        )

        event = self.adapter.dynamic_step("scroll")

        self.assertEqual(event[0], "internal_scroll")
        self.assertGreater(self.page.evaluate("document.querySelector('#people').scrollTop"), 0)
        self.assertEqual(self.page.evaluate("window.scrollY"), 0)

    def test_prefers_tight_people_list_over_scrollable_outer_layout(self):
        self.page.set_content(
            "<div id='layout' style='height: 200px; overflow-y: auto'>"
            "<div id='people' style='height: 100px; overflow-y: auto'>"
            "<div style='height: 700px'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "</div></div>"
            "<div style='height: 800px'></div>"
            "</div>"
        )

        event = self.adapter.dynamic_step("scroll")

        self.assertEqual(event[0], "internal_scroll")
        self.assertGreater(self.page.evaluate("document.querySelector('#people').scrollTop"), 0)
        self.assertEqual(self.page.evaluate("document.querySelector('#layout').scrollTop"), 0)

    def test_scroll_discovers_article_table_and_custom_people_containers(self):
        cases = {
            "article": (
                "<article id='people' class='people-results' style='height:100px;overflow-y:auto'>"
                "<div style='height:700px'><a href='/people/ada'>Ada Lovelace</a>"
                "<a href='/people/grace'>Grace Hopper</a></div></article>"
            ),
            "table": (
                "<table id='people' class='people-results' "
                "style='display:block;height:100px;overflow-y:auto'>"
                "<tbody style='display:block;height:700px'><tr><td>"
                "<a href='/people/ada'>Ada Lovelace</a>"
                "<a href='/people/grace'>Grace Hopper</a>"
                "</td></tr></tbody></table>"
            ),
            "custom": (
                "<faculty-results id='people' style='display:block;height:100px;overflow-y:auto'>"
                "<div style='height:700px'><a href='/people/ada'>Ada Lovelace</a>"
                "<a href='/people/grace'>Grace Hopper</a></div></faculty-results>"
            ),
        }
        for label, html in cases.items():
            with self.subTest(container=label):
                self.page.set_content(html)

                event = self.adapter.dynamic_step("scroll")

                self.assertEqual(event[0], "internal_scroll")
                self.assertGreater(
                    self.page.evaluate("document.querySelector('#people').scrollTop"), 0
                )

    def test_skips_exhausted_inner_scroller_for_useful_outer_people_scope(self):
        self.page.set_content(
            "<article id='outer' class='people-results' style='height:200px;overflow-y:auto'>"
            "<faculty-results id='inner' style='display:block;height:100px;overflow-y:auto'>"
            "<div style='height:700px'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "</div></faculty-results>"
            "<div style='height:800px'></div>"
            "</article>"
        )
        self.page.evaluate(
            "document.querySelector('#inner').scrollTop = "
            "document.querySelector('#inner').scrollHeight"
        )

        event = self.adapter.dynamic_step("scroll")

        self.assertEqual(event[0], "internal_scroll")
        self.assertGreater(self.page.evaluate("document.querySelector('#outer').scrollTop"), 0)

    def test_scrolls_window_when_no_people_list_is_scrollable(self):
        self.page.set_content(
            "<main>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<div style='height: 1500px'></div>"
            "</main>"
        )

        event = self.adapter.dynamic_step("scroll")

        self.assertEqual(event[0], "window_scroll")
        self.assertGreater(self.page.evaluate("window.scrollY"), 0)

    def test_exhausted_window_returns_no_scroll_action(self):
        self.page.set_content(
            "<main>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<div style='height: 1500px'></div>"
            "</main>"
        )
        self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        bottom = self.page.evaluate("window.scrollY")

        event = self.adapter.dynamic_step("scroll")

        self.assertIsNone(event)
        self.assertEqual(self.page.evaluate("window.scrollY"), bottom)

    def test_challenge_evidence_stops_before_click_or_scroll(self):
        self.page.set_content(
            "<title>Security check</title>"
            "<main>Verify you are human"
            "<section>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick='window.clicked = true'>Load more</button>"
            "</section><div style='height: 1500px'></div></main>"
        )

        event = self.adapter.dynamic_step("load_more")

        self.assertEqual(event[0], "verification_required")
        self.assertIsNone(self.page.evaluate("window.clicked"))
        self.assertEqual(self.page.evaluate("window.scrollY"), 0)

    def test_collect_waits_for_delayed_profile_within_global_deadline(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick=\"this.disabled = true; this.setAttribute('aria-busy', 'true'); "
            "this.insertAdjacentHTML('afterend', '&lt;span class=\\'spinner\\'&gt;Loading&lt;/span&gt;'); "
            "setTimeout(() => { this.insertAdjacentHTML("
            "'beforebegin', '&lt;a href=\\'/people/katherine\\'&gt;Katherine Johnson&lt;/a&gt;'); "
            "this.setAttribute('aria-busy', 'false'); "
            "this.parentElement.querySelector('.spinner').remove(); }, 600)\">"
            "Load more</button>"
            "</section>"
        )
        initial_html = self.page.content()
        adapter = _PlaywrightDynamicAdapter(self.page, timeout_ms=2000)

        snapshots, traces = collect_dynamic_snapshots(
            adapter,
            "https://local.invalid",
            initial_html,
            max_clicks=1,
            max_scrolls=0,
            timeout_ms=1500,
        )

        self.assertEqual(len(snapshots), 1)
        self.assertIn("/people/katherine", snapshots[0])
        self.assertEqual(traces[0].additions, (1,))

    def test_post_action_challenge_is_reported_with_single_click_round(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick=\"this.disabled = true; this.setAttribute('aria-busy', 'true'); "
            "this.insertAdjacentHTML('afterend', '&lt;span class=\\'spinner\\'&gt;Loading&lt;/span&gt;'); "
            "setTimeout(() => { document.body.innerHTML = "
            "'&lt;main&gt;Verify you are human&lt;/main&gt;'; }, 600)\">Load more</button>"
            "</section>"
        )
        initial_html = self.page.content()
        adapter = _PlaywrightDynamicAdapter(self.page, timeout_ms=1000)

        snapshots, traces = collect_dynamic_snapshots(
            adapter,
            "https://local.invalid",
            initial_html,
            max_clicks=1,
            max_scrolls=0,
            timeout_ms=1000,
        )

        self.assertEqual(snapshots, [])
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].stop_reason, "verification_required")

    def test_real_adapter_reaches_two_unchanged_clicks_before_global_deadline(self):
        self.page.set_content(
            "<section class='people-results'>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<button onclick='window.clicks = (window.clicks || 0) + 1'>"
            "Load more</button>"
            "</section>"
        )
        initial_html = self.page.content()
        adapter = _PlaywrightDynamicAdapter(self.page, timeout_ms=40)

        snapshots, traces = collect_dynamic_snapshots(
            adapter,
            "https://local.invalid",
            initial_html,
            max_clicks=10,
            max_scrolls=0,
            timeout_ms=1000,
        )

        self.assertEqual(snapshots, [])
        self.assertEqual(self.page.evaluate("window.clicks"), 2)
        self.assertEqual(traces[0].rounds, 2)
        self.assertEqual(traces[0].stop_reason, "two_unchanged_clicks")

    def test_real_adapter_reaches_three_unchanged_scrolls_before_global_deadline(self):
        self.page.set_content(
            "<main>"
            "<a href='/people/ada'>Ada Lovelace</a>"
            "<a href='/people/grace'>Grace Hopper</a>"
            "<div style='height: 5000px'></div>"
            "</main>"
        )
        initial_html = self.page.content()
        adapter = _PlaywrightDynamicAdapter(self.page, timeout_ms=40)

        snapshots, traces = collect_dynamic_snapshots(
            adapter,
            "https://local.invalid",
            initial_html,
            max_clicks=0,
            max_scrolls=10,
            timeout_ms=1000,
        )

        self.assertEqual(snapshots, [])
        self.assertEqual(traces[-1].rounds, 3)
        self.assertEqual(traces[-1].stop_reason, "three_unchanged_scrolls")


if __name__ == "__main__":
    unittest.main()
