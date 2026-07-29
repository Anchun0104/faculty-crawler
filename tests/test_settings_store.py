import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.settings_store import AppSettings, SettingsStore
from crawler.translation_settings import TranslationSettings


class SettingsStoreTests(unittest.TestCase):
    def test_settings_round_trip_and_reject_non_https_feishu_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "settings.json")
            settings = AppSettings(
                "D:/results", "https://example.feishu.cn/drive/folder/abc", False
            )
            store.save(settings)
            self.assertEqual(store.load(), settings)
            with self.assertRaises(ValueError):
                store.save(AppSettings("D:/results", "http://example.feishu.cn/folder", False))
            with self.assertRaises(ValueError):
                store.save(
                    AppSettings(
                        "D:/results",
                        "https://user:password@example.feishu.cn/folder",
                        False,
                    )
                )

    def test_settings_are_atomic_and_sensitive_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            store = SettingsStore(path)
            settings = AppSettings("D:/results", "https://example.feishu.cn/folder", True)
            store.save(settings)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            path.write_text(json.dumps({"output_dir": "x", "token": "SECRET"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load()

    def test_empty_feishu_url_is_rejected_and_failed_replace_preserves_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            store = SettingsStore(path)
            original = AppSettings("D:/one", "https://example.feishu.cn/one", False)
            store.save(original)
            with self.assertRaises(ValueError):
                store.save(AppSettings("D:/one", "", False))
            with patch("crawler.settings_store.os.replace", side_effect=OSError("denied")):
                with self.assertRaises(OSError):
                    store.save(AppSettings("D:/two", "https://example.feishu.cn/two", True))
            self.assertEqual(store.load(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_missing_settings_returns_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(SettingsStore(Path(temp_dir) / "settings.json").load())

    def test_legacy_settings_load_with_default_translation_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "output_dir": "D:/results",
                        "feishu_folder_url": "https://example.feishu.cn/folder",
                        "detailed_logs": False,
                    }
                ),
                encoding="utf-8",
            )

            settings = SettingsStore(path).load()

            self.assertEqual(settings.translation, TranslationSettings())

    def test_custom_local_translation_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = AppSettings(
                "D:/results",
                "https://example.feishu.cn/folder",
                False,
                TranslationSettings(
                    endpoint="http://localhost:5500",
                    cache_path=str(Path(temp_dir) / "translations.sqlite3"),
                    connect_timeout=3.0,
                    response_timeout=15.0,
                    retries=2,
                ),
            )

            store = SettingsStore(path)
            store.save(settings)

            self.assertEqual(store.load(), settings)

    def test_sensitive_fragment_parameters_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "settings.json")
            urls = (
                "https://example.feishu.cn/folder#ToKeN=SECRET",
                "https://example.feishu.cn/folder#/drive?Authorization=Bearer",
                "https://example.feishu.cn/folder#route?client_secret=SECRET",
            )
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    store.save(AppSettings("D:/results", url, False))


if __name__ == "__main__":
    unittest.main()
