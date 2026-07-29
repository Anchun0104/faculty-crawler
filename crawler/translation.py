from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class TranslationStatus(str, Enum):
    SUCCESS = "translation_success"
    CACHE_HIT = "cache_hit"
    NOT_NEEDED = "not_needed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    INVALID_RESPONSE = "invalid_response"
    FAILED = "translation_failed"


@dataclass(frozen=True)
class TranslationResult:
    status: TranslationStatus
    translated_text: str = ""
    detected_language: str = ""
    source_language: str = ""
    target_language: str = "en"
    engine: str = "libretranslate"
    engine_version: str = "1"
    error: str = ""


@dataclass(frozen=True)
class LanguageCapability:
    code: str
    name: str = ""
    targets: tuple[str, ...] = ()


def default_cache_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "FacultyCrawler"
    return root / "translation_cache.sqlite3"


class TranslationCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translations (
                    cache_key TEXT PRIMARY KEY,
                    original_title TEXT NOT NULL,
                    translated_title TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, cache_key: str) -> TranslationResult | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT translated_title, source_language, target_language, engine, engine_version "
                "FROM translations WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE translations SET last_used_at = ? WHERE cache_key = ?",
                (_now(), cache_key),
            )
            connection.commit()
        finally:
            connection.close()
        return TranslationResult(
            status=TranslationStatus.CACHE_HIT,
            translated_text=row[0],
            source_language=row[1],
            target_language=row[2],
            engine=row[3],
            engine_version=row[4],
        )

    def put(
        self,
        cache_key: str,
        *,
        original_title: str,
        translated_title: str,
        source_language: str,
        target_language: str,
        engine: str,
        engine_version: str,
    ) -> None:
        now = _now()
        connection = self._connect()
        try:
            connection.execute(
                """INSERT OR REPLACE INTO translations
                (cache_key, original_title, translated_title, source_language,
                 target_language, engine, engine_version, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cache_key,
                    original_title,
                    translated_title,
                    source_language,
                    target_language,
                    engine,
                    engine_version,
                    now,
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0


Transport = Callable[[str, str, dict | None, float], object]


class _NullTranslationCache:
    def get(self, cache_key: str) -> TranslationResult | None:
        return None

    def put(self, **kwargs) -> None:
        return None

    @property
    def size_bytes(self) -> int:
        return 0


def _default_cache() -> TranslationCache | _NullTranslationCache:
    try:
        return TranslationCache(default_cache_path())
    except (OSError, sqlite3.Error):
        return _NullTranslationCache()


class LibreTranslateClient:
    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:5000",
        *,
        target_language: str = "en",
        connect_timeout: float = 2.0,
        response_timeout: float = 10.0,
        retries: int = 1,
        cache: TranslationCache | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self._validate_endpoint(self.endpoint)
        self.target_language = target_language
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout
        self.retries = max(0, retries)
        self.cache = cache or _default_cache()
        self._transport = transport or (
            lambda method, path, payload, timeout: _urllib_transport(
                self.endpoint, method, path, payload, timeout
            )
        )
        self._capabilities: tuple[LanguageCapability, ...] | None = None
        self._capability_error: TranslationStatus | None = None

    @staticmethod
    def _validate_endpoint(endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LibreTranslate endpoint must use a loopback hostname")

    def check_capabilities(self) -> tuple[LanguageCapability, ...]:
        if self._capabilities is not None:
            return self._capabilities
        try:
            payload = self._request("GET", "/languages", None)
        except TimeoutError:
            self._capability_error = TranslationStatus.TIMEOUT
            return ()
        except (ConnectionError, OSError, urllib.error.URLError):
            self._capability_error = TranslationStatus.SERVICE_UNAVAILABLE
            return ()
        except Exception:
            self._capability_error = TranslationStatus.INVALID_RESPONSE
            return ()
        if not isinstance(payload, list):
            self._capability_error = TranslationStatus.INVALID_RESPONSE
            return ()
        capabilities: list[LanguageCapability] = []
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                self._capability_error = TranslationStatus.INVALID_RESPONSE
                return ()
            targets = item.get("targets", ())
            if not isinstance(targets, list) or not all(isinstance(value, str) for value in targets):
                targets = ()
            capabilities.append(LanguageCapability(item["code"], str(item.get("name", "")), tuple(targets)))
        self._capabilities = tuple(capabilities)
        return self._capabilities

    def translate(self, title: str, source_language: str = "auto") -> TranslationResult:
        original = " ".join(title.split())
        if not original:
            return TranslationResult(TranslationStatus.NOT_NEEDED, source_language=source_language)

        capabilities = self.check_capabilities()
        if self._capability_error is not None:
            return TranslationResult(self._capability_error, source_language=source_language)
        if source_language != "auto" and not any(item.code == source_language for item in capabilities):
            return TranslationResult(TranslationStatus.UNSUPPORTED_LANGUAGE, source_language=source_language)

        key = _cache_key(original, source_language, self.target_language)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        payload = {
            "q": original,
            "source": source_language,
            "target": self.target_language,
            "format": "text",
        }
        try:
            response = self._request_with_retries("POST", "/translate", payload)
        except TimeoutError:
            return TranslationResult(TranslationStatus.TIMEOUT, source_language=source_language)
        except (ConnectionError, OSError, urllib.error.URLError):
            return TranslationResult(TranslationStatus.SERVICE_UNAVAILABLE, source_language=source_language)
        except Exception as exc:
            return TranslationResult(TranslationStatus.FAILED, source_language=source_language, error=str(exc))

        if not isinstance(response, dict) or not isinstance(response.get("translatedText"), str) or not response["translatedText"].strip():
            return TranslationResult(TranslationStatus.INVALID_RESPONSE, source_language=source_language)
        detected = response.get("detectedLanguage")
        detected_language = detected.get("language", "") if isinstance(detected, dict) else ""
        result = TranslationResult(
            TranslationStatus.SUCCESS,
            response["translatedText"].strip(),
            detected_language,
            source_language,
            self.target_language,
        )
        self.cache.put(
            key,
            original_title=original,
            translated_title=result.translated_text,
            source_language=source_language,
            target_language=self.target_language,
            engine=result.engine,
            engine_version=result.engine_version,
        )
        return result

    def _request_with_retries(self, method: str, path: str, payload: dict | None) -> object:
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return self._request(method, path, payload)
            except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _request(self, method: str, path: str, payload: dict | None) -> object:
        timeout = self.connect_timeout if path == "/languages" else self.response_timeout
        return self._transport(method, path, payload, timeout)


def _cache_key(original: str, source_language: str, target_language: str) -> str:
    value = "\0".join((original, source_language, target_language, "libretranslate", "1"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _urllib_transport(endpoint: str, method: str, path: str, payload: dict | None, timeout: float) -> object:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ConnectionError(f"HTTP {exc.code}") from exc
