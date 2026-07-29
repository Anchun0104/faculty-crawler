from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import Mock

from crawler.local_translation_service import (
    LocalTranslationService,
    LocalTranslationServiceError,
    bundled_translation_service_path,
)
from crawler.translation_settings import TranslationSettings
from desktop_app import DesktopApp


class _Process:
    def __init__(self, *, returncode=None, wait_error: Exception | None = None) -> None:
        self.returncode = returncode
        self.wait_error = wait_error
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> int:
        if self.wait_error is not None:
            raise self.wait_error
        self.returncode = 0
        return 0


class LocalTranslationServiceTests(unittest.TestCase):
    def test_start_uses_loopback_and_returns_healthy_endpoint(self) -> None:
        calls: list[list[str]] = []
        process = _Process()
        endpoint = "http://127.0.0.1:51234"
        service = LocalTranslationService(
            Path("service.exe"),
            port=51234,
            launcher=lambda command: calls.append(command) or process,
            healthcheck=lambda value, timeout: value == endpoint,
            sleep=lambda seconds: None,
        )

        self.assertEqual(service.start(), endpoint)
        self.assertEqual(calls, [["service.exe", "--host", "127.0.0.1", "--port", "51234"]])
        self.assertEqual(service.endpoint, endpoint)

    def test_start_failure_cleans_up_child_process(self) -> None:
        process = _Process()
        service = LocalTranslationService(
            Path("service.exe"),
            port=51234,
            startup_timeout=0.0,
            launcher=lambda command: process,
            healthcheck=lambda endpoint, timeout: False,
            sleep=lambda seconds: None,
        )

        with self.assertRaises(LocalTranslationServiceError):
            service.start()

        self.assertTrue(process.terminated)
        self.assertIsNone(service.endpoint)

    def test_start_rejects_non_loopback_host(self) -> None:
        with self.assertRaises(ValueError):
            LocalTranslationService(Path("service.exe"), host="0.0.0.0")

    def test_stop_kills_unresponsive_process(self) -> None:
        process = _Process(wait_error=TimeoutError())
        service = LocalTranslationService(
            Path("service.exe"),
            port=51234,
            launcher=lambda command: process,
            healthcheck=lambda endpoint, timeout: True,
            sleep=lambda seconds: None,
        )
        service.start()

        service.stop()

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertIsNone(service.endpoint)

    def test_starting_twice_reuses_healthy_child(self) -> None:
        launches: list[list[str]] = []
        service = LocalTranslationService(
            Path("service.exe"),
            port=51234,
            launcher=lambda command: launches.append(command) or _Process(),
            healthcheck=lambda endpoint, timeout: True,
            sleep=lambda seconds: None,
        )

        first = service.start()
        second = service.start()

        self.assertEqual(first, second)
        self.assertEqual(len(launches), 1)

    def test_bundled_path_is_relative_to_the_application_directory(self) -> None:
        self.assertEqual(
            bundled_translation_service_path(Path("C:/FacultyCrawler")),
            Path("C:/FacultyCrawler/translation-service/LibreTranslate.exe"),
        )

    def test_desktop_start_replaces_configured_endpoint_with_managed_endpoint(self) -> None:
        app = DesktopApp.__new__(DesktopApp)
        app.translation_settings = TranslationSettings(endpoint="http://127.0.0.1:5000")
        app.translation_service = Mock()
        app.translation_service.start.return_value = "http://127.0.0.1:51234"

        app._start_local_translation_service()

        self.assertEqual(app.translation_settings.endpoint, "http://127.0.0.1:51234")
