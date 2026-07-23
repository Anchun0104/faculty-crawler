from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import struct
import tempfile
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol


_SESSION_LIFETIME = timedelta(days=30)
_METADATA_FIELDS = {"hostname", "saved_at", "last_used_at", "expires_at"}
_ENVELOPE_MAGIC = b"FCS1"
_ENVELOPE_PREFIX = struct.Struct("!4sH")
_ENVELOPE_LENGTH = struct.Struct("!Q")
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_INFINITE = 0xFFFFFFFF
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PAYLOAD_NAME = re.compile(
    r"(?P<hostname>[0-9a-f]{64})(?:\.[0-9a-f]{64})?\.session"
)
_DPAPI_CORRUPTION_ERRORS = {13, 87}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


class SessionProtectionError(RuntimeError):
    """Raised when the operating system cannot protect session data."""


class SessionCorruptionError(SessionProtectionError):
    """Raised when DPAPI identifies permanently invalid protected data."""


class SessionConflictError(RuntimeError):
    """Raised when another writer published the same session generation."""


class DataProtector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


@dataclass(frozen=True)
class SessionInfo:
    hostname: str
    saved_at: datetime
    last_used_at: datetime
    expires_at: datetime


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class WindowsDpapiProtector:
    _DESCRIPTION = "FacultyCrawler session"
    _UI_FORBIDDEN = 0x01

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, protect=True)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, protect=False)

    def _transform(self, data: bytes, *, protect: bool) -> bytes:
        if not isinstance(data, bytes):
            raise TypeError("session data must be bytes")
        if os.name != "nt":
            raise SessionProtectionError("Windows DPAPI is unavailable")

        operation = "protection" if protect else "unprotection"
        try:
            return self._transform_windows(data, protect=protect)
        except SessionProtectionError:
            raise
        except Exception:
            pass
        raise SessionProtectionError(f"Windows DPAPI {operation} failed")

    def _transform_windows(self, data: bytes, *, protect: bool) -> bytes:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_libraries(crypt32, kernel32)
        input_buffer = ctypes.create_string_buffer(data or b"\0")
        input_blob = _DataBlob(
            len(data),
            ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
        )
        output_blob = _DataBlob()
        description = wintypes.LPWSTR()

        if protect:
            succeeded = crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                self._DESCRIPTION,
                None,
                None,
                None,
                self._UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        else:
            succeeded = crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                ctypes.byref(description),
                None,
                None,
                None,
                self._UI_FORBIDDEN,
                ctypes.byref(output_blob),
            )
        error_code = ctypes.get_last_error() if not succeeded else 0

        try:
            if not succeeded:
                if not protect and error_code in _DPAPI_CORRUPTION_ERRORS:
                    raise SessionCorruptionError("protected session is invalid")
                operation = "protection" if protect else "unprotection"
                raise SessionProtectionError(f"Windows DPAPI {operation} failed")
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            if output_blob.pbData:
                kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            if description:
                kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))

    @staticmethod
    def _configure_libraries(crypt32, kernel32) -> None:
        blob_pointer = ctypes.POINTER(_DataBlob)
        crypt32.CryptProtectData.argtypes = [
            blob_pointer,
            wintypes.LPCWSTR,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob_pointer,
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,
            ctypes.POINTER(wintypes.LPWSTR),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob_pointer,
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p


class SessionStore:
    def __init__(
        self,
        directory: Path,
        protector: DataProtector | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._protector = (
            protector if protector is not None else WindowsDpapiProtector()
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        lock_digest = hashlib.sha256(str(self.directory).encode("utf-8")).hexdigest()
        lock_name = f"Local\\FacultyCrawlerSessionStore-{lock_digest}"
        self._cross_process_lock = lambda: _windows_named_mutex(lock_name)
        with _LOCKS_LOCK:
            self._lock = _LOCKS.setdefault(self.directory, threading.Lock())

    def save(self, hostname: str, data: bytes) -> SessionInfo:
        canonical = _normalize_hostname(hostname)
        if not isinstance(data, bytes):
            raise TypeError("session data must be bytes")
        metadata_path = self._metadata_path(canonical)
        with self._locked():
            saved_at = self._now()
            info = SessionInfo(
                canonical,
                saved_at,
                saved_at,
                saved_at + _SESSION_LIFETIME,
            )
            metadata = _encode_info(info)
            try:
                committed_metadata = metadata_path.read_bytes()
            except FileNotFoundError:
                committed_metadata = None
            if committed_metadata is not None:
                try:
                    committed = _decode_info(committed_metadata)
                except ValueError:
                    pass
                else:
                    if committed.hostname != canonical:
                        raise SessionConflictError(
                            "session hostname does not match manifest"
                        )
            protected = self._protect(
                _encode_envelope(canonical, metadata, data)
            )
            self._publish_generation(
                canonical,
                metadata,
                data,
                protected,
                replace_existing=True,
            )
            if committed_metadata != metadata:
                _atomic_write(metadata_path, metadata)
        return info

    def load(self, hostname: str) -> bytes | None:
        canonical = _normalize_hostname(hostname)
        metadata_path = self._metadata_path(canonical)
        with self._locked():
            try:
                metadata = metadata_path.read_bytes()
            except FileNotFoundError:
                return None
            try:
                info = _decode_info(metadata)
            except ValueError:
                self._remove_host_files(canonical)
                return None
            if info.hostname != canonical:
                self._remove_host_files(canonical)
                return None

            clock_now = self._now()
            if clock_now >= info.expires_at:
                self._remove_host_files(canonical)
                return None
            session_path = self._generation_path(canonical, metadata)
            try:
                protected = session_path.read_bytes()
            except FileNotFoundError:
                self._remove_host_files(canonical)
                return None
            try:
                envelope = self._unprotect(protected)
            except SessionCorruptionError:
                self._remove_host_files(canonical)
                return None
            data = _decode_envelope(envelope, canonical, metadata)
            if data is None:
                self._remove_host_files(canonical)
                return None

            last_used_at = max(clock_now, info.saved_at, info.last_used_at)
            updated = replace(info, last_used_at=last_used_at)
            updated_metadata = _encode_info(updated)
            if updated_metadata != metadata:
                updated_payload = self._protect(
                    _encode_envelope(canonical, updated_metadata, data)
                )
                self._publish_generation(
                    canonical,
                    updated_metadata,
                    data,
                    updated_payload,
                )
                _atomic_write(metadata_path, updated_metadata)
            return data

    def list_sessions(self) -> list[SessionInfo]:
        with self._locked():
            now = self._now()
            sessions: list[SessionInfo] = []
            for metadata_path in sorted(self.directory.glob("*.json")):
                try:
                    metadata = metadata_path.read_bytes()
                    info = _decode_info(metadata)
                except ValueError:
                    self._remove_manifest_entry(metadata_path)
                    continue
                if self._metadata_path(info.hostname) != metadata_path:
                    self._remove_manifest_entry(metadata_path)
                    continue
                current = self._generation_path(info.hostname, metadata)
                try:
                    current.stat()
                except FileNotFoundError:
                    self._remove_manifest_entry(metadata_path)
                    continue
                if now >= info.expires_at:
                    self._remove_manifest_entry(metadata_path)
                    continue
                sessions.append(info)
                self._remove_old_generations(metadata_path.stem, current)
            self._remove_orphan_generations()
            self._remove_temporary_files()
            return sorted(sessions, key=lambda item: item.hostname)

    def clear_site(self, hostname: str) -> None:
        canonical = _normalize_hostname(hostname)
        with self._locked():
            self._remove_host_files(canonical)

    def clear_all(self) -> None:
        with self._locked():
            for path in sorted(self.directory.glob("*.json")):
                path.unlink(missing_ok=True)
            for path in sorted(self.directory.glob("*.session")):
                path.unlink(missing_ok=True)
            for path in sorted(self.directory.glob("*.tmp")):
                path.unlink(missing_ok=True)

    def purge_expired(self) -> list[str]:
        with self._locked():
            now = self._now()
            removed: list[str] = []
            for metadata_path in sorted(self.directory.glob("*.json")):
                try:
                    metadata = metadata_path.read_bytes()
                    info = _decode_info(metadata)
                except ValueError:
                    self._remove_manifest_entry(metadata_path)
                    continue
                if self._metadata_path(info.hostname) != metadata_path:
                    self._remove_manifest_entry(metadata_path)
                    continue
                current = self._generation_path(info.hostname, metadata)
                try:
                    current.stat()
                except FileNotFoundError:
                    self._remove_manifest_entry(metadata_path)
                    continue
                if now >= info.expires_at:
                    self._remove_manifest_entry(metadata_path)
                    removed.append(info.hostname)
                    continue
                self._remove_old_generations(metadata_path.stem, current)
            self._remove_orphan_generations()
            self._remove_temporary_files()
            return sorted(removed)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @contextmanager
    def _locked(self):
        with self._lock:
            with self._cross_process_lock():
                yield

    def _protect(self, data: bytes) -> bytes:
        failed = False
        try:
            protected = self._protector.protect(data)
        except Exception:
            failed = True
            protected = None
        if failed:
            raise SessionProtectionError("session protection failed")
        if not isinstance(protected, bytes):
            raise SessionProtectionError("session protection returned invalid data")
        return protected

    def _unprotect(self, data: bytes) -> bytes:
        failed = False
        corrupt = False
        try:
            unprotected = self._protector.unprotect(data)
        except SessionCorruptionError:
            corrupt = True
            unprotected = None
        except Exception:
            failed = True
            unprotected = None
        if corrupt:
            raise SessionCorruptionError("protected session is invalid")
        if failed:
            raise SessionProtectionError("session unprotection failed")
        if not isinstance(unprotected, bytes):
            raise SessionProtectionError("session unprotection returned invalid data")
        return unprotected

    def _metadata_path(self, hostname: str) -> Path:
        return self.directory / f"{_hostname_digest(hostname)}.json"

    def _publish_generation(
        self,
        hostname: str,
        metadata: bytes,
        data: bytes,
        protected: bytes,
        *,
        replace_existing: bool = False,
    ) -> None:
        target = self._generation_path(hostname, metadata)
        try:
            _publish_immutable(target, protected)
            return
        except SessionConflictError:
            pass
        existing = self._unprotect(target.read_bytes())
        existing_data = _decode_envelope(existing, hostname, metadata)
        if existing_data is None:
            raise SessionConflictError("session generation already exists")
        if hmac.compare_digest(existing_data, data):
            return
        if replace_existing:
            _atomic_write(target, protected)
            return
        raise SessionConflictError("session generation already exists")

    def _generation_path(self, hostname: str, metadata: bytes) -> Path:
        generation = hashlib.sha256(metadata).hexdigest()
        return self.directory / f"{_hostname_digest(hostname)}.{generation}.session"

    def _remove_host_files(self, hostname: str) -> None:
        self._remove_group(_hostname_digest(hostname))

    def _remove_manifest_entry(self, metadata_path: Path) -> None:
        if _DIGEST.fullmatch(metadata_path.stem):
            self._remove_group(metadata_path.stem)
        else:
            metadata_path.unlink(missing_ok=True)

    def _remove_group(self, hostname_digest: str) -> None:
        if not _DIGEST.fullmatch(hostname_digest):
            raise ValueError("invalid session hostname digest")
        (self.directory / f"{hostname_digest}.json").unlink(missing_ok=True)
        (self.directory / f"{hostname_digest}.session").unlink(missing_ok=True)
        for path in sorted(self.directory.glob(f"{hostname_digest}.*.session")):
            path.unlink(missing_ok=True)
        for path in sorted(self.directory.glob(f".{hostname_digest}.*.tmp")):
            path.unlink(missing_ok=True)

    def _remove_old_generations(self, hostname_digest: str, current: Path) -> None:
        if not _DIGEST.fullmatch(hostname_digest):
            raise ValueError("invalid session hostname digest")
        legacy = self.directory / f"{hostname_digest}.session"
        if legacy != current:
            legacy.unlink(missing_ok=True)
        for path in sorted(self.directory.glob(f"{hostname_digest}.*.session")):
            if path != current:
                path.unlink(missing_ok=True)

    def _remove_orphan_generations(self) -> None:
        manifests = {
            path.stem
            for path in self.directory.glob("*.json")
            if _DIGEST.fullmatch(path.stem)
        }
        for path in sorted(self.directory.glob("*.session")):
            match = _PAYLOAD_NAME.fullmatch(path.name)
            if match is not None and match.group("hostname") not in manifests:
                path.unlink(missing_ok=True)

    def _remove_temporary_files(self) -> None:
        for path in self.directory.glob("*.tmp"):
            path.unlink(missing_ok=True)


@contextmanager
def _windows_named_mutex(name: str):
    if os.name != "nt":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise OSError("Windows session lock creation failed")
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, _INFINITE)
        if result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise OSError("Windows session lock acquisition failed")
        acquired = True
        yield
    finally:
        release_failed = acquired and not kernel32.ReleaseMutex(handle)
        close_failed = not kernel32.CloseHandle(handle)
        if release_failed or close_failed:
            raise OSError("Windows session lock release failed")


def _normalize_hostname(hostname: str) -> str:
    if not isinstance(hostname, str) or not hostname or hostname != hostname.strip():
        raise ValueError("hostname must be a canonical host name")
    if not hostname.isascii():
        raise ValueError("hostname must be a canonical host name")
    canonical = hostname.lower()
    if len(canonical) > 253:
        raise ValueError("hostname must be a canonical host name")
    labels = (
        canonical[:-1].split(".")
        if canonical.endswith(".")
        else canonical.split(".")
    )
    if any(
        not label
        or len(label) > 63
        or not label[0].isalnum()
        or not label[-1].isalnum()
        or any(not (character.isalnum() or character == "-") for character in label)
        for label in labels
    ):
        raise ValueError("hostname must be a canonical host name")
    return canonical


def _hostname_digest(hostname: str) -> str:
    return hashlib.sha256(hostname.encode("ascii")).hexdigest()


def _encode_info(info: SessionInfo) -> bytes:
    payload = asdict(info)
    for key in ("saved_at", "last_used_at", "expires_at"):
        payload[key] = payload[key].isoformat()
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")


def _decode_info(metadata: bytes) -> SessionInfo:
    try:
        payload = json.loads(metadata.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != _METADATA_FIELDS:
            raise ValueError("invalid session metadata")
        hostname = payload["hostname"]
        if _normalize_hostname(hostname) != hostname:
            raise ValueError("invalid session metadata")
        saved_at = _parse_timestamp(payload["saved_at"])
        last_used_at = _parse_timestamp(payload["last_used_at"])
        expires_at = _parse_timestamp(payload["expires_at"])
        if expires_at != saved_at + _SESSION_LIFETIME:
            raise ValueError("invalid session metadata")
        return SessionInfo(hostname, saved_at, last_used_at, expires_at)
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("invalid session metadata") from error


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid session timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("invalid session timestamp")
    return parsed.astimezone(timezone.utc)


def _encode_envelope(hostname: str, metadata: bytes, data: bytes) -> bytes:
    encoded_hostname = hostname.encode("ascii")
    metadata_digest = hashlib.sha256(metadata).digest()
    return (
        _ENVELOPE_PREFIX.pack(_ENVELOPE_MAGIC, len(encoded_hostname))
        + encoded_hostname
        + metadata_digest
        + _ENVELOPE_LENGTH.pack(len(data))
        + data
    )


def _decode_envelope(
    envelope: bytes,
    hostname: str,
    metadata: bytes,
) -> bytes | None:
    try:
        magic, hostname_length = _ENVELOPE_PREFIX.unpack_from(envelope)
        offset = _ENVELOPE_PREFIX.size
        encoded_hostname = envelope[offset : offset + hostname_length]
        offset += hostname_length
        metadata_digest = envelope[offset : offset + hashlib.sha256().digest_size]
        offset += hashlib.sha256().digest_size
        (data_length,) = _ENVELOPE_LENGTH.unpack_from(envelope, offset)
        offset += _ENVELOPE_LENGTH.size
        data = envelope[offset:]
    except (struct.error, ValueError):
        return None
    expected_hostname = hostname.encode("ascii")
    expected_digest = hashlib.sha256(metadata).digest()
    if (
        magic != _ENVELOPE_MAGIC
        or not hmac.compare_digest(encoded_hostname, expected_hostname)
        or not hmac.compare_digest(metadata_digest, expected_digest)
        or data_length != len(data)
    ):
        return None
    return data


def _publish_immutable(target: Path, data: bytes) -> None:
    temporary = _write_temporary(target, data)
    try:
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise SessionConflictError("session generation already exists") from error
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write(target: Path, data: bytes) -> None:
    temporary = _write_temporary(target, data)
    try:
        for attempt in range(3):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.01)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_temporary(target: Path, data: bytes) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
