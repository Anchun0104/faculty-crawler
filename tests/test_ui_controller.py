from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from crawler.models import TaskStatus
from crawler.task_store import StoredRun, StoredTask, TaskStore
from ui.controller import AppController
from ui.start_page import StartPage, _sanitized_input
from ui.theme import SECONDARY_BUTTON_MAP


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, tasks, *, timeout: int) -> bool:
        self.calls.append({"tasks": tuple(tasks), "timeout": timeout})
        return True


class AppControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runner = RecordingRunner()
        self.stop_calls = 0
        self.controller = AppController(
            Path(self.temp_dir.name),
            runner=self.runner,
            stop_after_current=self._record_stop,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _record_stop(self) -> None:
        self.stop_calls += 1

    def test_prepare_reports_exact_invalid_input_lines(self) -> None:
        state = self.controller.prepare(
            "https://example.edu/faculty\ninvalid\nftp://example.edu/list"
        )

        self.assertEqual(
            state.invalid_lines,
            ((2, "invalid"), (3, "ftp://example.edu/list")),
        )

    def test_blank_lines_preserve_original_line_numbers(self) -> None:
        state = self.controller.prepare(
            "\nhttps://one.example.edu/faculty\n\nnot-a-url\n"
        )

        self.assertEqual(state.invalid_lines, ((4, "not-a-url"),))

    def test_valid_count_and_runner_order_match_input(self) -> None:
        state = self.controller.prepare(
            "https://two.example.edu/faculty\nhttps://one.example.edu/faculty"
        )
        self.controller.start_batch()

        self.assertEqual(state.valid_count, 2)
        tasks = self.runner.calls[0]["tasks"]
        self.assertEqual(
            [task.url for task in tasks],
            [
                "https://two.example.edu/faculty",
                "https://one.example.edu/faculty",
            ],
        )

    def test_empty_or_all_invalid_input_cannot_start(self) -> None:
        for raw_urls in ("", "invalid\nftp://example.edu"):
            with self.subTest(raw_urls=raw_urls):
                self.controller.prepare(raw_urls)
                with self.assertRaises(ValueError):
                    self.controller.start_batch()

        self.assertEqual(self.runner.calls, [])

    def test_start_batch_uses_default_timeout_without_advanced_field(self) -> None:
        self.controller.prepare("https://example.edu/faculty")

        self.controller.start_batch()

        self.assertEqual(self.runner.calls[0]["timeout"], 30000)

    def test_internal_statuses_map_to_plain_chinese(self) -> None:
        self.assertEqual(
            self.controller.status_label(TaskStatus.VERIFICATION_REQUIRED),
            "等待人工验证",
        )
        self.assertEqual(
            self.controller.status_label(TaskStatus.REVIEW_RECOMMENDED),
            "已完成，建议检查",
        )

    def test_stop_after_current_delegates_once_and_updates_state(self) -> None:
        self.controller.prepare("https://example.edu/faculty")
        self.controller.start_batch()

        first = self.controller.stop_after_current()
        second = self.controller.stop_after_current()

        self.assertEqual(self.stop_calls, 1)
        self.assertTrue(first.stop_requested)
        self.assertEqual(second, first)

    def test_controller_constructs_without_importing_tkinter(self) -> None:
        self.assertNotIn("tkinter", AppController.__module__)
        self.assertEqual(self.controller.state.valid_count, 0)

    def test_sensitive_invalid_input_is_redacted_from_view_state(self) -> None:
        state = self.controller.prepare("token=DO-NOT-DISPLAY")

        self.assertNotIn("DO-NOT-DISPLAY", repr(state))
        self.assertEqual(state.invalid_lines, ((1, "token=<redacted>"),))

    def test_credentials_and_sensitive_url_keys_are_rejected_without_echo(self) -> None:
        raw = (
            "https://user:PASS@example.edu/faculty\n"
            "https://example.edu/faculty?token=QUERYSECRET\n"
            "https://example.edu/faculty#session=FRAGMENTSECRET"
        )

        state = self.controller.prepare(raw)

        self.assertEqual(state.valid_count, 0)
        rendered = repr(state)
        for secret in ("PASS", "QUERYSECRET", "FRAGMENTSECRET"):
            self.assertNotIn(secret, rendered)

    def test_non_whitelisted_query_keys_and_bare_credentials_are_rejected(self) -> None:
        raw = (
            "https://example.edu/faculty?key=KEYSECRET\n"
            "https://example.edu/faculty?code=CODESECRET\n"
            "https://example.edu/faculty?foo=FOOSECRET\n"
            "alice:TOPSECRET@example.edu"
        )

        state = self.controller.prepare(raw)

        self.assertEqual(state.valid_count, 0)
        combined = repr(state) + repr(self.controller.tasks)
        for secret in ("KEYSECRET", "CODESECRET", "FOOSECRET", "TOPSECRET"):
            self.assertNotIn(secret, combined)
        widget_text = _sanitized_input(raw, state.invalid_lines)
        self.assertNotIn("TOPSECRET", widget_text)
        self.assertIn("<credentials>@example.edu", widget_text)

    def test_rejected_secret_never_reaches_stored_task_json(self) -> None:
        safe_url = "https://example.edu/faculty?page=2"
        self.controller.prepare(
            safe_url + "\nhttps://example.edu/faculty?foo=DO-NOT-STORE"
        )
        task = self.controller.tasks[0]
        store = TaskStore(Path(self.temp_dir.name) / "tasks")
        store.save(
            StoredRun(
                "run-safe",
                [
                    StoredTask(
                        "task-safe",
                        task.url,
                        str(task.output_path),
                        TaskStatus.PENDING,
                    )
                ],
            )
        )

        persisted = "".join(
            path.read_text(encoding="utf-8")
            for path in (Path(self.temp_dir.name) / "tasks").glob("*.json")
        )
        self.assertEqual(task.url, safe_url)
        self.assertNotIn("DO-NOT-STORE", persisted)

    def test_finished_stopped_batch_keeps_stopped_outcome(self) -> None:
        self.controller.prepare("https://example.edu/faculty")
        self.controller.start_batch()

        state = self.controller.finish_batch("批量任务结束：已停止 1。", stopped=True)

        self.assertEqual(state.status_symbol, "■")
        self.assertIn("已停止 1", state.status_text)

    def test_safe_url_keeps_exact_identity(self) -> None:
        url = "https://example.edu/Faculty?department=Law#directory"
        self.controller.prepare(url)
        self.controller.start_batch()

        self.assertEqual(self.runner.calls[0]["tasks"][0].url, url)

    def test_normal_return_start_failure_rolls_back_running_state(self) -> None:
        controller = AppController(
            self.temp_dir.name,
            runner=lambda _tasks, *, timeout: False,
        )
        controller.prepare("https://example.edu/faculty")

        state = controller.start_batch()

        self.assertFalse(state.running)
        self.assertTrue(state.can_start)
        self.assertEqual(state.status_symbol, "×")

    def test_controller_creates_worker_and_drains_routed_events(self) -> None:
        handled: list[str] = []

        def target() -> None:
            self.controller.events.put(type("Event", (), {"kind": "done"})())

        self.assertTrue(self.controller.launch_worker("batch", target=target))
        self.controller.worker("batch").join(2)
        count = self.controller.drain_events({"done": lambda _event: handled.append("done")})

        self.assertEqual(count, 1)
        self.assertEqual(handled, ["done"])


class StartPageBehaviorTests(unittest.TestCase):
    def test_scroll_callback_keeps_scrollbar_and_gutter_synchronized(self) -> None:
        page = object.__new__(StartPage)
        calls: list[tuple[object, ...]] = []
        page.scrollbar = type("Scrollbar", (), {"set": lambda _self, *args: calls.append(args)})()
        page.line_gutter = type(
            "Gutter",
            (),
            {"yview_moveto": lambda _self, value: calls.append(("gutter", value))},
        )()

        page._on_url_scroll("0.25", "0.75")

        self.assertEqual(calls, [("0.25", "0.75"), ("gutter", 0.25)])

    def test_secondary_button_has_legible_disabled_colors(self) -> None:
        self.assertEqual(SECONDARY_BUTTON_MAP["foreground"][0][0], "disabled")
        self.assertNotEqual(
            SECONDARY_BUTTON_MAP["foreground"][0][1],
            SECONDARY_BUTTON_MAP["background"][0][1],
        )

    def test_invalid_secret_is_replaced_before_remaining_in_input_widget(self) -> None:
        rendered = _sanitized_input(
            "https://user:PASS@example.edu/faculty\ninvalid",
            ((1, "https://example.edu/faculty"), (2, "invalid")),
        )

        self.assertEqual(rendered, "https://example.edu/faculty\ninvalid")
        self.assertNotIn("PASS", rendered)


if __name__ == "__main__":
    unittest.main()
