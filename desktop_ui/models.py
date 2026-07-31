"""Immutable, framework-independent values exchanged with desktop views."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UrlPreparation:
    valid_urls: tuple[str, ...]
    duplicate_lines: tuple[tuple[int, str], ...]
    invalid_lines: tuple[tuple[int, str], ...]

    @property
    def can_start(self) -> bool:
        return bool(self.valid_urls) and not self.invalid_lines


@dataclass(frozen=True)
class NewCrawlRequest:
    urls: tuple[str, ...]
    output_dir: Path
    school_name: str = ""
    discipline: str = "General Faculty"
    use_ai: bool = False
    routine_model: str = "deepseek-v4-flash"
    escalation_model: str = "deepseek-v4-pro"
    budget_usd: float = 20.0


@dataclass(frozen=True)
class SaveAiSettings:
    enabled: bool
    provider: str = "local"
    base_url: str = ""
    model: str = ""
    # None preserves the encrypted value; an empty string explicitly removes it.
    api_key: str | None = None


@dataclass(frozen=True)
class AiSettingsView:
    enabled: bool
    provider: str
    base_url: str
    model: str
    key_configured: bool
