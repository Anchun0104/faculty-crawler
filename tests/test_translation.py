import tempfile
import unittest
from pathlib import Path

from crawler.translation import LibreTranslateClient, TranslationCache, TranslationStatus


class TranslationTests(unittest.TestCase):
    def test_successful_translation_is_cached(self) -> None:
        calls = []

        def transport(method, path, payload, timeout):
            calls.append((method, path, payload))
            if path == "/languages":
                return [{"code": "ar", "name": "Arabic", "targets": ["en"]}]
            return {"translatedText": "Associate Professor", "detectedLanguage": {"language": "ar"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = TranslationCache(Path(temp_dir) / "translations.sqlite3")
            client = LibreTranslateClient(transport=transport, cache=cache)
            first = client.translate("Arabic title", source_language="ar")
            second = client.translate("Arabic title", source_language="ar")

        self.assertEqual(first.status, TranslationStatus.SUCCESS)
        self.assertEqual(second.status, TranslationStatus.CACHE_HIT)
        self.assertEqual(second.translated_text, "Associate Professor")
        self.assertEqual(sum(path == "/translate" for _, path, _ in calls), 1)

    def test_service_failure_returns_status_instead_of_raising(self) -> None:
        def failing_transport(method, path, payload, timeout):
            raise TimeoutError("offline")

        client = LibreTranslateClient(transport=failing_transport)
        result = client.translate("unknown title", source_language="xx")
        self.assertEqual(result.status, TranslationStatus.TIMEOUT)
        self.assertEqual(result.translated_text, "")

    def test_non_loopback_endpoint_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LibreTranslateClient(endpoint="https://translation.example.com")

    def test_unsupported_language_is_reported(self) -> None:
        def transport(method, path, payload, timeout):
            return [{"code": "fr", "name": "French", "targets": ["en"]}]

        client = LibreTranslateClient(transport=transport)
        result = client.translate("Professor", source_language="xx")
        self.assertEqual(result.status, TranslationStatus.UNSUPPORTED_LANGUAGE)


if __name__ == "__main__":
    unittest.main()
