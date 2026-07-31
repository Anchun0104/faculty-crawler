from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from faculty_workflow.ai_settings import AiSettingsStore, ApiKeyStore, ProviderConfiguration
from faculty_workflow.providers import DeepSeekProvider, OpenAICompatibleProvider, ProviderResult


class ReversibleProtector:
    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"protected:"):
            raise ValueError("not protected")
        return value[len(b"protected:"):][::-1]


class AiSettingsTests(unittest.TestCase):
    def test_connection_uses_configured_model_without_persisting_a_prompt_or_key(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = []

            def generate_policy(self, discipline, model):
                self.calls.append((discipline, model))
                return ProviderResult({}, model, "connection", 0, 0, 0, 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = AiSettingsStore(root, protector=ReversibleProtector())
            provider = Provider()

            result = store.test_connection(ProviderConfiguration.deepseek(), "secret-key", provider=provider)

            self.assertEqual(result.response_id, "connection")
            self.assertEqual(provider.calls, [("General Faculty", "deepseek-v4-flash")])
            self.assertEqual(list(root.iterdir()), [])

    def test_configures_deepseek_preset_and_keeps_key_out_of_json_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = AiSettingsStore(root, protector=ReversibleProtector())

            store.save(ProviderConfiguration.deepseek(model="deepseek-v4-pro"), "secret-key")

            configuration, key = store.load()
            self.assertTrue(configuration.enabled)
            self.assertEqual(configuration.base_url, "https://api.deepseek.com")
            self.assertEqual(configuration.model, "deepseek-v4-pro")
            self.assertEqual(key, "secret-key")
            self.assertNotIn("secret-key", (root / "ai-settings.json").read_text(encoding="utf-8"))
            self.assertIn(b"protected:", (root / "ai-key.bin").read_bytes())
            self.assertIsInstance(store.build_provider(configuration, key), DeepSeekProvider)

    def test_configures_generic_chat_completions_provider_without_url_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AiSettingsStore(Path(temp_dir), protector=ReversibleProtector())
            configuration = ProviderConfiguration(
                enabled=True,
                provider="compatible",
                base_url="https://api.example.com/v1",
                model="custom-chat-model",
            )

            provider = store.build_provider(configuration, "secret-key")

            self.assertIsInstance(provider, OpenAICompatibleProvider)
            self.assertEqual(provider.endpoint, "https://api.example.com/v1/chat/completions")
            with self.assertRaisesRegex(ValueError, "https"):
                ProviderConfiguration(True, "compatible", "http://api.example.com", "custom")

    def test_delete_key_keeps_non_secret_configuration_and_switches_to_local_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = AiSettingsStore(root, protector=ReversibleProtector())
            store.save(ProviderConfiguration.deepseek(), "secret-key")

            store.delete_key()
            store.save(ProviderConfiguration.local(), "")

            configuration, key = store.load()
            self.assertFalse(configuration.enabled)
            self.assertEqual(key, "")
            self.assertFalse((root / "ai-key.bin").exists())


class ApiKeyStoreTests(unittest.TestCase):
    def test_empty_key_removes_encrypted_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ApiKeyStore(Path(temp_dir) / "key.bin", protector=ReversibleProtector())
            store.save("secret-key")
            store.save("")

            self.assertEqual(store.load(), "")
            self.assertFalse((Path(temp_dir) / "key.bin").exists())


if __name__ == "__main__":
    unittest.main()
