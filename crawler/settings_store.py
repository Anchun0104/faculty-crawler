from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from crawler.privacy import is_sensitive_key


_FIELDS = {"output_dir", "feishu_folder_url", "detailed_logs"}


@dataclass(frozen=True)
class AppSettings:
    output_dir: str
    feishu_folder_url: str
    detailed_logs: bool


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("settings are invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("settings are invalid")
        if any(is_sensitive_key(str(key)) for key in payload):
            raise ValueError("settings contain a sensitive key")
        if set(payload) != _FIELDS:
            raise ValueError("settings are invalid")
        return _validate_settings(AppSettings(**payload))

    def save(self, settings: AppSettings) -> None:
        if not isinstance(settings, AppSettings):
            raise TypeError("settings must be an AppSettings instance")
        settings = _validate_settings(settings)
        payload = json.dumps(asdict(settings), ensure_ascii=False, indent=2)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise


def _validate_settings(settings: AppSettings) -> AppSettings:
    if not isinstance(settings.output_dir, str):
        raise TypeError("output_dir must be a string")
    if not isinstance(settings.feishu_folder_url, str):
        raise TypeError("feishu_folder_url must be a string")
    if type(settings.detailed_logs) is not bool:
        raise TypeError("detailed_logs must be a boolean")
    parsed = urlparse(settings.feishu_folder_url)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or _has_sensitive_parameters(parsed.query)
        or _has_sensitive_parameters(parsed.fragment)
    ):
        raise ValueError("feishu_folder_url must be an HTTPS URL")
    return settings


def _has_sensitive_parameters(value: str) -> bool:
    return any(
        is_sensitive_key(key) or is_sensitive_key(key.casefold())
        for key, _ in parse_qsl(value, keep_blank_values=True)
    )
