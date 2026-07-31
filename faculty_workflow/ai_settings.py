from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from faculty_workflow.providers import DeepSeekProvider, ModelProvider, OpenAICompatibleProvider
from faculty_workflow.session_store import DataProtector, WindowsDPAPIProtector


@dataclass(frozen=True)
class ProviderConfiguration:
    enabled: bool = False
    provider: str = "local"
    base_url: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        if self.provider not in {"deepseek", "compatible"}:
            raise ValueError("AI provider must be deepseek or compatible")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("AI base_url must use https")
        if not self.model.strip():
            raise ValueError("AI model is required when AI is enabled")

    @classmethod
    def local(cls) -> "ProviderConfiguration":
        return cls()

    @classmethod
    def deepseek(cls, *, model: str = "deepseek-v4-flash") -> "ProviderConfiguration":
        return cls(True, "deepseek", "https://api.deepseek.com", model)

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


class ApiKeyStore:
    """Stores only encrypted API-key bytes; configuration metadata stays separate."""

    def __init__(self, path: str | Path, *, protector: DataProtector | None = None) -> None:
        self.path = Path(path)
        self.protector = protector or WindowsDPAPIProtector()

    def save(self, key: str) -> None:
        value = key.strip()
        if not value:
            self.delete()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.protector.protect(value.encode("utf-8")))

    def load(self) -> str:
        try:
            return self.protector.unprotect(self.path.read_bytes()).decode("utf-8")
        except FileNotFoundError:
            return ""

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class AiSettingsStore:
    def __init__(self, directory: str | Path, *, protector: DataProtector | None = None) -> None:
        self.directory = Path(directory)
        self.configuration_path = self.directory / "ai-settings.json"
        self.keys = ApiKeyStore(self.directory / "ai-key.bin", protector=protector)

    def load(self) -> tuple[ProviderConfiguration, str]:
        return self.load_configuration(), self.keys.load()

    def load_configuration(self) -> ProviderConfiguration:
        try:
            raw = json.loads(self.configuration_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ProviderConfiguration.local()
        if not isinstance(raw, dict) or "api_key" in raw or set(raw) - {"enabled", "provider", "base_url", "model"}:
            raise ValueError("AI settings are invalid")
        return ProviderConfiguration(**raw)

    def key_configured(self) -> bool:
        """Return key presence without decrypting or returning its plaintext value."""
        try:
            return self.keys.path.stat().st_size > 0
        except FileNotFoundError:
            return False

    def save(self, configuration: ProviderConfiguration, api_key: str | None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.configuration_path.write_text(
            json.dumps(asdict(configuration), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        if not configuration.enabled:
            self.keys.delete()
        elif api_key is not None:
            self.keys.save(api_key)

    def delete_key(self) -> None:
        self.keys.delete()

    def test_connection(
        self,
        configuration: ProviderConfiguration,
        api_key: str,
        *,
        provider: ModelProvider | None = None,
    ):
        active_provider = provider or self.build_provider(configuration, api_key)
        if active_provider is None:
            raise ValueError("AI is disabled")
        return active_provider.generate_policy("General Faculty", configuration.model)

    def build_provider(self, configuration: ProviderConfiguration, api_key: str) -> ModelProvider | None:
        if not configuration.enabled:
            return None
        if configuration.provider == "deepseek":
            return DeepSeekProvider(api_key=api_key, endpoint=configuration.endpoint)
        return OpenAICompatibleProvider(api_key=api_key, endpoint=configuration.endpoint)
