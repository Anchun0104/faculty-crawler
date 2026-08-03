from __future__ import annotations

import threading
import unittest


class _Facade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def begin_verification(self, _review_id: str) -> None:
        self.calls.append(("begin", threading.get_ident()))

    def finish_verification(self, _review_id: str) -> None:
        self.calls.append(("finish", threading.get_ident()))

    def defer_verification(self, _review_id: str) -> None:
        self.calls.append(("defer", threading.get_ident()))


class VerificationExecutorTests(unittest.TestCase):
    def test_browser_lifecycle_and_shutdown_use_one_long_lived_thread(self):
        from desktop_ui.verification_executor import VerificationExecutor

        facade = _Facade()
        executor = VerificationExecutor(facade)
        executor.submit("begin", "7").result(2)
        executor.submit("finish", "7").result(2)
        executor.submit("begin", "8").result(2)
        executor.submit("defer", "8").result(2)
        executor.shutdown()

        self.assertEqual([name for name, _thread in facade.calls], ["begin", "finish", "begin", "defer", "defer"])
        self.assertEqual(len({thread for _name, thread in facade.calls}), 1)
        self.assertNotEqual(facade.calls[0][1], threading.get_ident())
