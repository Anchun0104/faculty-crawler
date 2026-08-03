from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


class DesktopWorkerPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        from desktop_ui.workers import WorkerPool

        self.worker_pool = WorkerPool(max_thread_count=1)

    def tearDown(self) -> None:
        self.worker_pool.shutdown()

    def test_worker_failure_is_redacted_before_ui_signal(self) -> None:
        spy = QSignalSpy(self.worker_pool.failed)
        release = self._submit_after_delay(lambda: (_ for _ in ()).throw(RuntimeError("token=secret")))
        threading.Timer(0.02, release.set).start()

        self.assertTrue(self._wait_for(spy))
        self.assertNotIn("secret", spy.at(0)[0])

    def test_succeeded_signal_is_delivered_to_the_main_thread(self) -> None:
        observed: list[object] = []
        spy = QSignalSpy(self.worker_pool.succeeded)
        self.worker_pool.succeeded.connect(lambda _value: observed.append(QThread.currentThread()))

        release = self._submit_after_delay(lambda: "done")
        threading.Timer(0.02, release.set).start()

        self.assertTrue(self._wait_for(spy))
        self.assertEqual(observed, [APP.thread()])

    def test_stop_after_current_skips_queued_work(self) -> None:
        release = threading.Event()
        started = threading.Event()
        calls: list[str] = []
        succeeded = QSignalSpy(self.worker_pool.succeeded)

        def first() -> str:
            calls.append("first")
            started.set()
            release.wait(2)
            return "first"

        self.worker_pool.submit(first)
        self.assertTrue(started.wait(1000))
        self.worker_pool.submit(lambda: calls.append("second"))
        self.worker_pool.request_stop_after_current()
        release.set()

        self.assertTrue(self._wait_for(succeeded))
        self.assertTrue(self.worker_pool.wait_for_done(2000))
        self.assertEqual(calls, ["first"])

    def test_command_can_raise_verification_required_without_completing(self) -> None:
        from desktop_ui.workers import VerificationRequired

        verification = QSignalSpy(self.worker_pool.verification_required)
        succeeded = QSignalSpy(self.worker_pool.succeeded)

        release = self._submit_after_delay(lambda: (_ for _ in ()).throw(VerificationRequired("review-7")))
        threading.Timer(0.02, release.set).start()

        self.assertTrue(self._wait_for(verification))
        self.assertEqual(verification.at(0), ["review-7"])
        self.assertEqual(succeeded.count(), 0)

    def _submit_after_delay(self, command):
        started = threading.Event()
        release = threading.Event()

        def delayed_command():
            started.set()
            release.wait(1)
            return command()

        self.worker_pool.submit(delayed_command)
        self.assertTrue(started.wait(1000))
        return release

    @staticmethod
    def _wait_for(spy: QSignalSpy, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            APP.processEvents()
            if spy.count():
                return True
            time.sleep(0.01)
        return False


if __name__ == "__main__":
    unittest.main()
