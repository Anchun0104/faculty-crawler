import tempfile
import unittest
from pathlib import Path

from crawler.translation import TranslationStatus
from crawler.translation_settings import TranslationSettings


class TranslationSettingsTests(unittest.TestCase):
    def test_defaults_create_the_existing_local_client_contract(self):
        settings = TranslationSettings()

        client = settings.create_client()

        self.assertEqual(client.endpoint, "http://127.0.0.1:5000")
        self.assertEqual(client.connect_timeout, 2.0)
        self.assertEqual(client.response_timeout, 10.0)
        self.assertEqual(client.retries, 1)
        self.assertEqual(client.target_language, "en")

    def test_custom_loopback_settings_create_client_with_custom_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "translation.sqlite3"
            settings = TranslationSettings(
                endpoint="http://localhost:5500",
                cache_path=str(cache_path),
                connect_timeout=3.5,
                response_timeout=12.5,
                retries=2,
            )

            client = settings.create_client()

            self.assertEqual(client.endpoint, "http://localhost:5500")
            self.assertEqual(client.cache.path, cache_path)
            self.assertEqual(client.connect_timeout, 3.5)
            self.assertEqual(client.response_timeout, 12.5)
            self.assertEqual(client.retries, 2)

    def test_rejects_remote_or_credential_bearing_endpoints(self):
        for endpoint in (
            "https://translation.example.com",
            "http://user:secret@127.0.0.1:5000",
            "http://127.0.0.1:5000?token=secret",
            "http://127.0.0.1:5000#secret",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    TranslationSettings(endpoint=endpoint)

    def test_rejects_invalid_timing_and_retry_values(self):
        for kwargs in (
            {"connect_timeout": 0},
            {"response_timeout": 0},
            {"retries": -1},
            {"cache_path": ""},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    TranslationSettings(**kwargs)


if __name__ == "__main__":
    unittest.main()
