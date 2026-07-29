from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from crawler.translation import (
    LibreTranslateClient,
    TranslationCache,
    default_cache_path,
)


@dataclass(frozen=True)
class TranslationSettings:
    endpoint: str = "http://127.0.0.1:5000"
    cache_path: str = str(default_cache_path())
    connect_timeout: float = 2.0
    response_timeout: float = 10.0
    retries: int = 1
    target_language: str = "en"

    def __post_init__(self) -> None:
        LibreTranslateClient._validate_endpoint(self.endpoint)
        if not isinstance(self.cache_path, str) or not self.cache_path.strip():
            raise ValueError("translation cache path is required")
        if isinstance(self.connect_timeout, bool) or self.connect_timeout <= 0:
            raise ValueError("translation connect timeout must be positive")
        if isinstance(self.response_timeout, bool) or self.response_timeout <= 0:
            raise ValueError("translation response timeout must be positive")
        if isinstance(self.retries, bool) or not isinstance(self.retries, int) or self.retries < 0:
            raise ValueError("translation retries must be a non-negative integer")
        if not isinstance(self.target_language, str) or not self.target_language.strip():
            raise ValueError("translation target language is required")

    def create_client(self) -> LibreTranslateClient:
        try:
            cache = TranslationCache(Path(self.cache_path))
        except (OSError, sqlite3.Error):
            cache = None
        return LibreTranslateClient(
            endpoint=self.endpoint,
            target_language=self.target_language,
            connect_timeout=float(self.connect_timeout),
            response_timeout=float(self.response_timeout),
            retries=self.retries,
            cache=cache,
        )
