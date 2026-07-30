from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse


class SessionProtectionError(RuntimeError):
    pass


class DataProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class WindowsDPAPIProtector:
    """Use the current Windows user's DPAPI key; no application key is stored."""

    _UI_FORBIDDEN = 0x01

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def protect(self, value: bytes) -> bytes:
        return self._transform(value, encrypt=True)

    def unprotect(self, value: bytes) -> bytes:
        return self._transform(value, encrypt=False)

    def _transform(self, value: bytes, *, encrypt: bool) -> bytes:
        if os.name != "nt":
            raise SessionProtectionError("Windows DPAPI is unavailable")
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob = self._Blob
        crypt32.CryptProtectData.argtypes = [ctypes.POINTER(blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(blob)]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(blob)]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        raw = ctypes.create_string_buffer(value or b"\0")
        source = blob(len(value), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
        target = blob()
        if encrypt:
            ok = crypt32.CryptProtectData(ctypes.byref(source), "Faculty workflow session", None, None, None, self._UI_FORBIDDEN, ctypes.byref(target))
        else:
            ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, self._UI_FORBIDDEN, ctypes.byref(target))
        try:
            if not ok:
                raise SessionProtectionError("Windows could not protect the site session")
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            if target.pbData:
                kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


@dataclass(frozen=True)
class SessionInfo:
    hostname: str
    saved_at: str
    expires_at: str


class ProtectedSessionStore:
    """Encrypted, site-isolated Playwright storage states with a 30-day lifetime."""

    def __init__(
        self,
        directory: str | Path,
        *,
        protector: DataProtector | None = None,
        lifetime: timedelta = timedelta(days=30),
        now: callable | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.protector = protector or WindowsDPAPIProtector()
        self.lifetime = lifetime
        self.now = now or (lambda: datetime.now(timezone.utc))

    def save(self, hostname: str, storage_state: dict) -> SessionInfo:
        host = _hostname(hostname)
        if not isinstance(storage_state, dict):
            raise ValueError("Browser storage state is invalid")
        current = self.now().astimezone(timezone.utc)
        expires = current + self.lifetime
        payload = json.dumps(storage_state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self.protector.protect(payload)
        self._data_path(host).write_bytes(encrypted)
        info = SessionInfo(host, current.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds"))
        self._meta_path(host).write_text(json.dumps(info.__dict__, ensure_ascii=True), encoding="utf-8")
        return info

    def load(self, hostname: str) -> dict | None:
        host = _hostname(hostname)
        try:
            raw_info = json.loads(self._meta_path(host).read_text(encoding="utf-8"))
            info = SessionInfo(**raw_info)
            expires = datetime.fromisoformat(info.expires_at)
            if self.now().astimezone(timezone.utc) >= expires.astimezone(timezone.utc):
                self.clear(host)
                return None
            decrypted = self.protector.unprotect(self._data_path(host).read_bytes())
            state = json.loads(decrypted.decode("utf-8"))
            return state if isinstance(state, dict) else None
        except FileNotFoundError:
            return None
        except (UnicodeError, ValueError, json.JSONDecodeError, SessionProtectionError):
            self.clear(host)
            return None

    def list(self) -> list[SessionInfo]:
        results: list[SessionInfo] = []
        for path in self.directory.glob("*.json"):
            try:
                info = SessionInfo(**json.loads(path.read_text(encoding="utf-8")))
                if self.load(info.hostname) is not None:
                    results.append(info)
            except (TypeError, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
        return sorted(results, key=lambda item: item.hostname)

    def clear(self, hostname: str) -> None:
        host = _hostname(hostname)
        self._meta_path(host).unlink(missing_ok=True)
        self._data_path(host).unlink(missing_ok=True)

    def _meta_path(self, hostname: str) -> Path:
        return self.directory / f"{hostname}.json"

    def _data_path(self, hostname: str) -> Path:
        return self.directory / f"{hostname}.state"


def _hostname(value: str) -> str:
    host = (urlparse(value).hostname or value).strip().casefold().rstrip(".")
    if not host or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for char in host):
        raise ValueError("Invalid session hostname")
    return host
