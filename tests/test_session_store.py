import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import crawler.session_store as session_store
from crawler.session_store import (
    SessionProtectionError,
    SessionStore,
    WindowsDpapiProtector,
)


class ReversingProtector:
    def protect(self, data):
        return data[::-1]

    def unprotect(self, data):
        return data[::-1]


class FailingProtector:
    def protect(self, data):
        raise RuntimeError("protector failed")

    def unprotect(self, data):
        raise RuntimeError("protected payload is invalid")


class CorruptProtector(ReversingProtector):
    def unprotect(self, data):
        raise session_store.SessionCorruptionError("protected session is invalid")


class FakeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeDpapiLibraries:
    def __init__(self, *, protect_succeeds=True, unprotect_succeeds=True):
        self.protect_succeeds = protect_succeeds
        self.unprotect_succeeds = unprotect_succeeds
        self.calls = []
        self.freed = []
        self.buffers = []
        self.CryptProtectData = FakeFunction(self._protect)
        self.CryptUnprotectData = FakeFunction(self._unprotect)
        self.LocalFree = FakeFunction(self._local_free)

    def library(self, name, **kwargs):
        return self if name in {"crypt32", "kernel32"} else None

    def _set_output(self, output, size):
        buffer = ctypes.create_string_buffer(bytes(size))
        self.buffers.append(buffer)
        output.cbData = size
        output.pbData = ctypes.cast(buffer, type(output.pbData))

    def _protect(self, input_blob, description, entropy, reserved, prompt, flags, output):
        self.calls.append(("protect", input_blob._obj.cbData, description, flags))
        self._set_output(output._obj, 7)
        return self.protect_succeeds

    def _unprotect(
        self, input_blob, description, entropy, reserved, prompt, flags, output
    ):
        self.calls.append(("unprotect", input_blob._obj.cbData, None, flags))
        description._obj.value = "FacultyCrawler session"
        self._set_output(output._obj, 5)
        return self.unprotect_succeeds

    def _local_free(self, pointer):
        self.freed.append(pointer.value)
        return None


def generation_payload(root, hostname):
    digest = hashlib.sha256(hostname.encode("ascii")).hexdigest()
    matches = list(root.glob(f"{digest}*.session"))
    if len(matches) != 1:
        raise AssertionError("expected exactly one payload generation")
    return matches[0]


def hostname_with_digest_prefix(prefix):
    for index in range(10000):
        hostname = f"site-{index}.example.edu"
        if hashlib.sha256(hostname.encode("ascii")).hexdigest().startswith(prefix):
            return hostname
    raise AssertionError("digest prefix not found")


class SessionStoreTests(unittest.TestCase):
    def test_round_trip_does_not_leave_plain_cookie_on_disk(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("faculty.example.edu", b'{"cookies":[{"value":"SECRET"}]}')
            disk = next(root.glob("*.session")).read_bytes()
            loaded = store.load("faculty.example.edu")
        self.assertFalse(b"SECRET" in disk)
        self.assertTrue(loaded is not None and b"SECRET" in loaded)

    def test_metadata_uses_hostname_digest_and_only_public_session_info(self):
        now = datetime(2026, 7, 22, 12, 30, tzinfo=timezone.utc)
        hostname = "faculty.example.edu"
        digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            saved = store.save(hostname, b"state")
            metadata = json.loads((root / f"{digest}.json").read_text(encoding="utf-8"))
            payload = generation_payload(root, hostname).read_bytes()
        self.assertEqual(
            set(metadata),
            {"hostname", "saved_at", "last_used_at", "expires_at"},
        )
        self.assertEqual(metadata["hostname"], hostname)
        self.assertEqual(saved.hostname, hostname)
        self.assertEqual(saved.saved_at, now)
        self.assertEqual(saved.last_used_at, now)
        self.assertEqual(saved.expires_at, now + timedelta(days=30))
        self.assertFalse(b"state" in payload)

    def test_swapped_protected_payloads_are_rejected_without_returning_data(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("first.example.edu", b"first-state")
            store.save("second.example.edu", b"second-state")
            first_path = generation_payload(root, "first.example.edu")
            second_path = generation_payload(root, "second.example.edu")
            first_bytes = first_path.read_bytes()
            second_bytes = second_path.read_bytes()
            first_path.write_bytes(second_bytes)
            second_path.write_bytes(first_bytes)
            first_loaded = store.load("first.example.edu")
            second_loaded = store.load("second.example.edu")
        self.assertIsNone(first_loaded)
        self.assertIsNone(second_loaded)

    def test_manifest_commit_failure_preserves_previous_complete_generation(self):
        current = [datetime(2026, 7, 22, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"existing-state")
            current[0] += timedelta(seconds=1)
            original_replace = os.replace

            def fail_manifest(source, target):
                if Path(target).suffix == ".json":
                    raise OSError("manifest unavailable")
                return original_replace(source, target)

            with patch("crawler.session_store.os.replace", side_effect=fail_manifest):
                with self.assertRaisesRegex(OSError, "manifest unavailable"):
                    store.save("example.edu", b"replacement-state")
            loaded = store.load("example.edu")
        self.assertTrue(loaded is not None and loaded.startswith(b"existing"))

    def test_last_used_commit_failure_preserves_old_pair_and_retry_recovers(self):
        current = [datetime(2026, 7, 22, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state")
            current[0] += timedelta(seconds=1)
            with patch(
                "crawler.session_store.os.replace",
                side_effect=OSError("manifest unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "manifest unavailable"):
                    store.load("example.edu")
            loaded = store.load("example.edu")
            info = store.list_sessions()[0]
        self.assertIsNotNone(loaded)
        self.assertEqual(info.last_used_at, current[0])

    def test_cross_store_torn_generation_is_not_accepted(self):
        first_now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        second_now = first_now + timedelta(seconds=1)
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
            tempfile.TemporaryDirectory() as target_dir,
        ):
            first_root = Path(first_dir)
            second_root = Path(second_dir)
            target_root = Path(target_dir)
            SessionStore(
                first_root, ReversingProtector(), clock=lambda: first_now
            ).save("example.edu", b"first-state")
            SessionStore(
                second_root, ReversingProtector(), clock=lambda: second_now
            ).save("example.edu", b"second-state")
            manifest = next(second_root.glob("*.json"))
            target_manifest = target_root / manifest.name
            target_manifest.write_bytes(manifest.read_bytes())
            source_payload = generation_payload(first_root, "example.edu")
            expected_payload = generation_payload(second_root, "example.edu")
            (target_root / expected_payload.name).write_bytes(source_payload.read_bytes())
            loaded = SessionStore(
                target_root, ReversingProtector(), clock=lambda: second_now
            ).load("example.edu")
        self.assertIsNone(loaded)

    def test_hostname_keeps_security_distinct_dns_forms_isolated(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            dotted = store.save("Faculty.Example.EDU.", b"dotted")
            plain = store.save("faculty.example.edu", b"plain")
            self.assertEqual(dotted.hostname, "faculty.example.edu.")
            self.assertEqual(plain.hostname, "faculty.example.edu")
            self.assertIsNotNone(store.load("FACULTY.EXAMPLE.EDU."))
            self.assertIsNotNone(store.load("FACULTY.EXAMPLE.EDU"))
            self.assertEqual(len(store.list_sessions()), 2)
            self.assertEqual(len(list(root.glob("*.json"))), 2)

    def test_hostname_rejects_unicode_instead_of_using_idna2003_mapping(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir), ReversingProtector(), clock=lambda: now)
            store.save("fass.de", b"ascii")
            store.save("xn--fa-hia.de", b"punycode")
            with self.assertRaises(ValueError):
                store.save("faß.de", b"unicode")
            self.assertEqual(
                [info.hostname for info in store.list_sessions()],
                ["fass.de", "xn--fa-hia.de"],
            )

    def test_unsafe_hostname_values_are_rejected(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(Path(temp_dir), ReversingProtector(), clock=lambda: now)
            for hostname in (
                "",
                "../escape",
                "https://example.edu",
                "example.edu/path",
                "example.edu\\path",
                "example.edu:443",
                ".example.edu",
                "example..edu",
                "example.edu..",
                "-example.edu",
                "example-.edu",
                " example.edu",
            ):
                with self.subTest(hostname=hostname):
                    with self.assertRaises(ValueError):
                        store.save(hostname, b"state")
                    with self.assertRaises(ValueError):
                        store.load(hostname)

    def test_load_updates_last_used_without_extending_expiry(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(
                Path(temp_dir), ReversingProtector(), clock=lambda: current[0]
            )
            original = store.save("example.edu", b"state")
            current[0] += timedelta(days=12)
            self.assertIsNotNone(store.load("example.edu"))
            listed = store.list_sessions()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].last_used_at, current[0])
        self.assertEqual(listed[0].expires_at, original.expires_at)

    def test_purge_removes_sessions_after_30_days(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state")
            current[0] += timedelta(days=31)
            removed = store.purge_expired()
            remaining = list(root.iterdir())
        self.assertEqual(removed, ["example.edu"])
        self.assertEqual(remaining, [])

    def test_load_at_expiry_removes_pair_without_unprotecting(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state")
            current[0] += timedelta(days=30)
            expired_store = SessionStore(root, FailingProtector(), clock=lambda: current[0])
            loaded = expired_store.load("example.edu")
            remaining = list(root.iterdir())
        self.assertIsNone(loaded)
        self.assertEqual(remaining, [])

    def test_corrupt_mismatched_and_incomplete_pairs_are_removed_safely(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("first.example.edu", b"state-one")
            store.save("second.example.edu", b"state-two")
            first = hashlib.sha256(b"first.example.edu").hexdigest()
            second = hashlib.sha256(b"second.example.edu").hexdigest()
            (root / f"{first}.json").write_bytes((root / f"{second}.json").read_bytes())
            self.assertIsNone(store.load("first.example.edu"))
            self.assertIsNotNone(store.load("second.example.edu"))

            (root / f"{first}.json").write_text("not json", encoding="utf-8")
            (root / f"{first}.session").write_bytes(b"orphan")
            self.assertEqual(store.list_sessions()[0].hostname, "second.example.edu")
            self.assertFalse((root / f"{first}.json").exists())
            self.assertFalse((root / f"{first}.session").exists())

            (root / f"{first}.session").write_bytes(b"orphan")
            self.assertEqual(store.purge_expired(), [])
            self.assertFalse((root / f"{first}.session").exists())

    def test_invalid_manifest_stems_remove_only_the_manifest(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            prefix_hostname = hostname_with_digest_prefix("a")
            unrelated_hostname = hostname_with_digest_prefix("c")
            store.save(prefix_hostname, bytes(4))
            store.save(unrelated_hostname, bytes(4))
            prefix_payload = generation_payload(root, prefix_hostname)
            unrelated_payload = generation_payload(root, unrelated_hostname)
            short_manifest = root / "a.json"
            hidden_manifest = root / ".json"
            short_manifest.write_text("invalid", encoding="utf-8")
            hidden_manifest.write_text("invalid", encoding="utf-8")
            store.list_sessions()
            state = (
                short_manifest.exists(),
                hidden_manifest.exists(),
                prefix_payload.exists(),
                unrelated_payload.exists(),
            )
        self.assertEqual(state, (False, False, True, True))

    def test_valid_group_cleanup_does_not_delete_longer_digest_prefix(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            digest = "a" * 64
            manifest = root / f"{digest}.json"
            exact_payload = root / f"{digest}.session"
            generation_payload_path = root / f"{digest}.generation.session"
            longer_prefix = root / f"{digest}f.generation.session"
            manifest.write_text("invalid", encoding="utf-8")
            exact_payload.write_bytes(bytes(4))
            generation_payload_path.write_bytes(bytes(4))
            longer_prefix.write_bytes(bytes(4))
            store.purge_expired()
            state = (
                manifest.exists(),
                exact_payload.exists(),
                generation_payload_path.exists(),
                longer_prefix.exists(),
            )
        self.assertEqual(state, (False, False, False, True))

    def test_temporary_unprotect_failure_is_sanitized_and_preserves_pair(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            good_store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            good_store.save(
                "example.edu", b"state"
            )
            failing_store = SessionStore(root, FailingProtector(), clock=lambda: now)
            with self.assertRaisesRegex(
                SessionProtectionError, "session unprotection failed"
            ) as raised:
                failing_store.load("example.edu")
            remaining = list(root.iterdir())
            loaded = good_store.load("example.edu")
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(len(remaining), 2)
        self.assertIsNotNone(loaded)

    def test_authenticated_corruption_is_discarded_after_dpapi_classifies_it(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            SessionStore(root, ReversingProtector(), clock=lambda: now).save(
                "example.edu", b"state"
            )
            loaded = SessionStore(root, CorruptProtector(), clock=lambda: now).load(
                "example.edu"
            )
            remaining = list(root.iterdir())
        self.assertIsNone(loaded)
        self.assertEqual(remaining, [])

    def test_temporary_manifest_and_payload_io_failures_preserve_pair(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("example.edu", b"state")
            metadata_path = next(root.glob("*.json"))
            payload_path = generation_payload(root, "example.edu")
            original_read_bytes = Path.read_bytes

            def fail_manifest(path):
                if path == metadata_path:
                    raise PermissionError("sharing violation")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", fail_manifest):
                with self.assertRaisesRegex(PermissionError, "sharing violation"):
                    store.load("example.edu")
            self.assertTrue(metadata_path.exists() and payload_path.exists())

            def fail_payload(path):
                if path == payload_path:
                    raise PermissionError("sharing violation")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", fail_payload):
                with self.assertRaisesRegex(PermissionError, "sharing violation"):
                    store.load("example.edu")
            self.assertTrue(metadata_path.exists() and payload_path.exists())
            self.assertIsNotNone(store.load("example.edu"))

    def test_protect_failure_is_sanitized_and_preserves_existing_pair(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            good_store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            good_store.save("example.edu", b"existing-state")
            failing_store = SessionStore(root, FailingProtector(), clock=lambda: now)
            with self.assertRaisesRegex(
                SessionProtectionError, "session protection failed"
            ) as raised:
                failing_store.save("example.edu", b"replacement-state")
            loaded = good_store.load("example.edu")
        self.assertIsNone(raised.exception.__context__)
        self.assertTrue(loaded is not None and loaded.startswith(b"existing"))

    def test_clear_site_and_clear_all_remove_both_files_and_orphans(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("first.example.edu", b"state-one")
            store.save("second.example.edu", b"state-two")
            store.clear_site("first.example.edu")
            self.assertEqual(
                [item.hostname for item in store.list_sessions()],
                ["second.example.edu"],
            )
            (root / ("a" * 64 + ".session")).write_bytes(b"orphan")
            (root / ".interrupted.tmp").write_bytes(b"temporary")
            store.clear_all()
            remaining = list(root.iterdir())
        self.assertEqual(remaining, [])

    def test_atomic_writes_flush_and_clean_temporary_files_on_failure(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            events = []
            original_replace = os.replace
            original_link = os.link

            def record_replace(source, target):
                events.append(("replace", Path(target).suffix))
                return original_replace(source, target)

            def record_link(source, target):
                events.append(("publish", Path(target).suffix))
                return original_link(source, target)

            with (
                patch(
                    "crawler.session_store.os.fsync",
                    side_effect=lambda _: events.append(("fsync", None)),
                ),
                patch("crawler.session_store.os.replace", side_effect=record_replace),
                patch("crawler.session_store.os.link", side_effect=record_link),
            ):
                store.save("example.edu", b"state")
            self.assertEqual(
                events,
                [
                    ("fsync", None),
                    ("publish", ".session"),
                    ("fsync", None),
                    ("replace", ".json"),
                ],
            )

            empty_root = root / "failure"
            failing = SessionStore(empty_root, ReversingProtector(), clock=lambda: now)
            with patch("crawler.session_store.os.link", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(OSError, "disk error"):
                    failing.save("other.example.edu", b"new-state")
            self.assertEqual(list(empty_root.iterdir()), [])

    def test_manifest_replace_retries_a_temporary_windows_sharing_failure(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            original_replace = os.replace
            attempts = []

            def replace_after_sharing_failure(source, target):
                attempts.append(Path(target).suffix)
                if len(attempts) == 1:
                    raise PermissionError(13, "sharing violation")
                return original_replace(source, target)

            with patch(
                "crawler.session_store.os.replace",
                side_effect=replace_after_sharing_failure,
            ):
                store.save("example.edu", b"state")
            loaded = store.load("example.edu")
        self.assertEqual(attempts, [".json", ".json"])
        self.assertIsNotNone(loaded)

    def test_same_clock_sequential_saves_atomically_replace_one_generation(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            first = store.save("example.edu", b"state-one")
            second = store.save("example.edu", b"state-two")
            loaded = store.load("example.edu")
            listed = store.list_sessions()[0]
            payloads = list(root.glob("*.session"))
        self.assertEqual(second.saved_at, first.saved_at)
        self.assertEqual(second.expires_at, second.saved_at + timedelta(days=30))
        self.assertTrue(loaded is not None and loaded.endswith(b"two"))
        self.assertGreaterEqual(listed.last_used_at, second.last_used_at)
        self.assertEqual(len(payloads), 1)

    def test_same_generation_replace_failure_preserves_existing_pair(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            store.save("example.edu", b"existing-state")
            existing_payload = generation_payload(root, "example.edu")
            existing_bytes = existing_payload.read_bytes()
            original_replace = os.replace

            def fail_generation_replace(source, target):
                if Path(target).suffix == ".session":
                    raise OSError("generation unavailable")
                return original_replace(source, target)

            with patch(
                "crawler.session_store.os.replace",
                side_effect=fail_generation_replace,
            ):
                with self.assertRaisesRegex(OSError, "generation unavailable"):
                    store.save("example.edu", b"replacement-state")
            loaded = store.load("example.edu")
            retained_bytes = existing_payload.read_bytes()
            remaining_temporary = list(root.glob("*.tmp"))
        self.assertEqual(retained_bytes, existing_bytes)
        self.assertTrue(loaded is not None and loaded.startswith(b"existing"))
        self.assertEqual(remaining_temporary, [])

    def test_save_expiry_is_anchored_to_clock_after_future_last_use(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state-one")
            current[0] = datetime(2026, 7, 30, tzinfo=timezone.utc)
            self.assertIsNotNone(store.load("example.edu"))
            current[0] = datetime(2026, 7, 1, tzinfo=timezone.utc)
            saved = store.save("example.edu", b"state-two")
            loaded = store.load("example.edu")
        self.assertEqual(saved.saved_at, current[0])
        self.assertEqual(saved.last_used_at, current[0])
        self.assertEqual(saved.expires_at, current[0] + timedelta(days=30))
        self.assertTrue(loaded is not None and loaded.endswith(b"two"))

    def test_two_store_instances_serialize_concurrent_saves(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stores = [
                SessionStore(root, ReversingProtector(), clock=lambda: now),
                SessionStore(root, ReversingProtector(), clock=lambda: now),
            ]
            barrier = threading.Barrier(2)
            errors = []
            results = []

            def save(store, state, marker):
                try:
                    barrier.wait(timeout=5)
                    info = store.save("example.edu", state)
                    results.append((info.saved_at, marker))
                except Exception as error:
                    errors.append(type(error).__name__)

            threads = [
                threading.Thread(target=save, args=(stores[0], b"state-one", 1)),
                threading.Thread(target=save, args=(stores[1], b"state-two", 2)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            loaded = stores[0].load("example.edu")
            listed = stores[0].list_sessions()[0]
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2)
        self.assertEqual(
            sorted(saved_at for saved_at, _ in results),
            [now, now],
        )
        self.assertIn(loaded, {b"state-one", b"state-two"})
        self.assertGreaterEqual(listed.last_used_at, now)

    def test_process_interleaving_commits_only_a_matching_generation(self):
        times = [
            datetime(2026, 7, 22, tzinfo=timezone.utc),
            datetime(2026, 7, 22, tzinfo=timezone.utc) + timedelta(seconds=1),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stores = [
                SessionStore(root, ReversingProtector(), clock=lambda: times[0]),
                SessionStore(root, ReversingProtector(), clock=lambda: times[1]),
            ]
            for store in stores:
                store._lock = threading.Lock()
                store._cross_process_lock = nullcontext
            barrier = threading.Barrier(2)
            replace_calls = []
            errors = []
            original_replace = os.replace

            def interleave_manifests(source, target):
                if Path(target).suffix == ".json":
                    replace_calls.append(Path(source))
                    if len(replace_calls) <= 2:
                        barrier.wait(timeout=5)
                return original_replace(source, target)

            def save(store, state):
                try:
                    store.save("example.edu", state)
                except Exception as error:
                    errors.append(
                        (
                            type(error).__name__,
                            getattr(error, "winerror", None),
                            getattr(error, "errno", None),
                        )
                    )

            with patch(
                "crawler.session_store.os.replace", side_effect=interleave_manifests
            ):
                threads = [
                    threading.Thread(target=save, args=(stores[0], b"first-state")),
                    threading.Thread(target=save, args=(stores[1], b"second-state")),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            verifier = SessionStore(
                root, ReversingProtector(), clock=lambda: times[1]
            )
            info = verifier.list_sessions()[0]
            loaded = verifier.load("example.edu")
        self.assertTrue(
            (info.saved_at == times[0] and loaded.startswith(b"first"))
            or (info.saved_at == times[1] and loaded.startswith(b"second"))
        )

    def test_directory_mutex_serializes_independent_store_instances(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stores = [
                SessionStore(root, ReversingProtector(), clock=lambda: now),
                SessionStore(root, ReversingProtector(), clock=lambda: now),
            ]
            for store in stores:
                store._lock = threading.Lock()
            barrier = threading.Barrier(2)
            counter_lock = threading.Lock()
            active = [0]
            maximum = [0]
            errors = []
            original_atomic_write = session_store._atomic_write

            def observe_atomic_write(target, data):
                with counter_lock:
                    active[0] += 1
                    maximum[0] = max(maximum[0], active[0])
                time.sleep(0.03)
                try:
                    return original_atomic_write(target, data)
                finally:
                    with counter_lock:
                        active[0] -= 1

            def save(store, hostname):
                try:
                    barrier.wait(timeout=5)
                    store.save(hostname, bytes(4))
                except Exception as error:
                    errors.append(type(error).__name__)

            with patch(
                "crawler.session_store._atomic_write",
                side_effect=observe_atomic_write,
            ):
                threads = [
                    threading.Thread(
                        target=save,
                        args=(stores[0], "first.example.edu"),
                    ),
                    threading.Thread(
                        target=save,
                        args=(stores[1], "second.example.edu"),
                    ),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(maximum[0], 1)

    @unittest.skipUnless(os.name == "nt", "Windows named mutex regression")
    def test_two_os_processes_save_same_clock_without_conflict(self):
        worker = """
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from crawler.session_store import SessionStore

class Protector:
    def protect(self, data):
        return data[::-1]
    def unprotect(self, data):
        return data[::-1]

root = Path(sys.argv[1])
gate = Path(sys.argv[2])
size = int(sys.argv[3])
while not gate.exists():
    time.sleep(0.005)
now = datetime(2026, 7, 22, tzinfo=timezone.utc)
SessionStore(root, Protector(), clock=lambda: now).save(
    "example.edu",
    bytes(size),
)
"""
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gate = root / "start"
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", worker, str(root), str(gate), str(size)],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for size in (4, 5)
            ]
            gate.touch()
            results = [process.communicate(timeout=15) for process in processes]
            return_codes = [process.returncode for process in processes]
            store = SessionStore(root, ReversingProtector(), clock=lambda: now)
            loaded = store.load("example.edu")
            info = store.list_sessions()[0]
        self.assertEqual(return_codes, [0, 0])
        self.assertEqual(results, [("", ""), ("", "")])
        self.assertTrue(loaded is not None and len(loaded) in {4, 5})
        self.assertEqual(info.saved_at, now)

    def test_purge_and_clear_surface_deletion_failures_for_retry(self):
        current = [datetime(2026, 7, 1, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("expired.example.edu", b"state")
            current[0] += timedelta(days=31)
            original_unlink = Path.unlink

            def fail_manifest(path, *args, **kwargs):
                if path.suffix == ".json":
                    raise PermissionError("sharing violation")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_manifest):
                with self.assertRaisesRegex(PermissionError, "sharing violation"):
                    store.purge_expired()
            self.assertEqual(store.purge_expired(), ["expired.example.edu"])

            store.save("clear.example.edu", b"state")
            payload_path = generation_payload(root, "clear.example.edu")

            def fail_payload(path, *args, **kwargs):
                if path == payload_path:
                    raise PermissionError("sharing violation")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_payload):
                with self.assertRaisesRegex(PermissionError, "sharing violation"):
                    store.clear_site("clear.example.edu")
            self.assertTrue(payload_path.exists())
            store.clear_site("clear.example.edu")
            self.assertFalse(payload_path.exists())

    def test_purge_reclaims_old_generation_without_removing_current(self):
        current = [datetime(2026, 7, 22, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SessionStore(root, ReversingProtector(), clock=lambda: current[0])
            store.save("example.edu", b"state")
            current[0] += timedelta(seconds=1)
            self.assertIsNotNone(store.load("example.edu"))
            self.assertEqual(len(list(root.glob("*.session"))), 2)
            self.assertEqual(store.purge_expired(), [])
            self.assertEqual(len(list(root.glob("*.session"))), 1)
            self.assertIsNotNone(store.load("example.edu"))

    def test_clock_must_return_timezone_aware_datetime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(
                Path(temp_dir),
                ReversingProtector(),
                clock=lambda: datetime(2026, 7, 22),
            )
            with self.assertRaises(ValueError):
                store.save("example.edu", b"state")


class WindowsDpapiProtectorTests(unittest.TestCase):
    def test_non_windows_platform_has_no_plaintext_fallback(self):
        with patch("crawler.session_store.os.name", "posix"):
            protector = WindowsDpapiProtector()
            with self.assertRaisesRegex(SessionProtectionError, "Windows DPAPI"):
                protector.protect(b"state")
            with self.assertRaisesRegex(SessionProtectionError, "Windows DPAPI"):
                protector.unprotect(b"protected")

    def test_windows_library_failure_is_wrapped_without_exception_context(self):
        protector = WindowsDpapiProtector()
        opaque = bytes(5)
        with patch("crawler.session_store.ctypes.WinDLL", side_effect=OSError("missing")):
            with self.assertRaisesRegex(
                SessionProtectionError, "Windows DPAPI protection failed"
            ) as raised:
                protector.protect(opaque)
        self.assertIsNone(raised.exception.__context__)

    def test_fake_windows_dll_verifies_dpapi_abi_and_frees_all_outputs(self):
        libraries = FakeDpapiLibraries()
        protector = WindowsDpapiProtector()
        with patch("crawler.session_store.ctypes.WinDLL", side_effect=libraries.library):
            protected = protector.protect(bytes(4))
            unprotected = protector.unprotect(bytes(3))
        self.assertEqual(
            libraries.calls,
            [
                ("protect", 4, "FacultyCrawler session", 1),
                ("unprotect", 3, None, 1),
            ],
        )
        self.assertEqual(len(protected), 7)
        self.assertEqual(len(unprotected), 5)
        self.assertEqual(len(libraries.freed), 3)
        self.assertEqual(len(libraries.CryptProtectData.argtypes), 7)
        self.assertEqual(len(libraries.CryptUnprotectData.argtypes), 7)

    def test_fake_windows_dll_frees_outputs_when_dpapi_returns_false(self):
        libraries = FakeDpapiLibraries(
            protect_succeeds=False,
            unprotect_succeeds=False,
        )
        protector = WindowsDpapiProtector()
        with patch("crawler.session_store.ctypes.WinDLL", side_effect=libraries.library):
            with self.assertRaisesRegex(SessionProtectionError, "protection failed"):
                protector.protect(bytes(4))
            with self.assertRaisesRegex(SessionProtectionError, "unprotection failed"):
                protector.unprotect(bytes(3))
        self.assertEqual(len(libraries.freed), 3)

    def test_fake_windows_dll_classifies_invalid_protected_data_as_corrupt(self):
        libraries = FakeDpapiLibraries(unprotect_succeeds=False)
        protector = WindowsDpapiProtector()
        with (
            patch("crawler.session_store.ctypes.WinDLL", side_effect=libraries.library),
            patch("crawler.session_store.ctypes.get_last_error", return_value=13),
        ):
            with self.assertRaises(session_store.SessionCorruptionError):
                protector.unprotect(bytes(3))
        self.assertEqual(len(libraries.freed), 2)

    def test_fake_windows_dll_classifies_invalid_parameter_as_corrupt(self):
        libraries = FakeDpapiLibraries(unprotect_succeeds=False)
        protector = WindowsDpapiProtector()
        with (
            patch("crawler.session_store.ctypes.WinDLL", side_effect=libraries.library),
            patch("crawler.session_store.ctypes.get_last_error", return_value=87),
        ):
            with self.assertRaises(session_store.SessionCorruptionError):
                protector.unprotect(bytes(3))
        self.assertEqual(len(libraries.freed), 2)

    def test_invalid_parameter_corruption_removes_store_pair(self):
        now = datetime(2026, 7, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            SessionStore(root, ReversingProtector(), clock=lambda: now).save(
                "example.edu", bytes(4)
            )
            store = SessionStore(root, WindowsDpapiProtector(), clock=lambda: now)
            store._cross_process_lock = nullcontext
            libraries = FakeDpapiLibraries(unprotect_succeeds=False)
            with (
                patch(
                    "crawler.session_store.ctypes.WinDLL",
                    side_effect=libraries.library,
                ),
                patch("crawler.session_store.ctypes.get_last_error", return_value=87),
            ):
                loaded = store.load("example.edu")
            remaining = list(root.iterdir())
        self.assertIsNone(loaded)
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()
