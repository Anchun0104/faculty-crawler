from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

from crawler.models import TaskStatus


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TASK_ID = _RUN_ID
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_INFINITE = 0xFFFFFFFF
_RUN_FIELDS = {"run_id", "tasks", "schema_version"}
_TASK_FIELDS = {
    "task_id",
    "url",
    "output_path",
    "status",
    "record_count",
    "error",
}


class TaskStoreConflictError(RuntimeError):
    pass


@dataclass
class StoredTask:
    task_id: str
    url: str
    output_path: str
    status: TaskStatus
    record_count: int = 0
    error: str = ""


@dataclass
class StoredRun:
    run_id: str
    tasks: list[StoredTask]
    schema_version: int = 1


class TaskStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_digest = hashlib.sha256(
            str(self.directory).casefold().encode("utf-8")
        ).hexdigest()
        lock_name = f"Local\\FacultyCrawlerTaskStore-{lock_digest}"
        self._cross_process_lock = lambda: _windows_named_mutex(lock_name)
        with _LOCKS_LOCK:
            self._lock = _LOCKS.setdefault(self.directory, threading.Lock())

    def save(self, run: StoredRun) -> None:
        _validate_run(run, run.run_id)
        with self._locked():
            self._save_unlocked(run)

    def load(self, run_id: str) -> StoredRun:
        self._run_path(run_id)
        with self._locked():
            return self._load_unlocked(run_id)

    def resolve_original_url(self, run_id: str, task_id: str) -> str:
        self._run_path(run_id)
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must be a safe identifier")
        with self._locked():
            run = self._load_unlocked(run_id)
            for task in run.tasks:
                if task.task_id == task_id:
                    return task.url
        raise KeyError("stored task was not found")

    def update_task(
        self,
        run_id: str,
        task_id: str,
        status: TaskStatus,
        *,
        output_path: str | None = None,
        record_count: int | None = None,
        error: str | None = None,
    ) -> StoredTask:
        self._run_path(run_id)
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id must be a safe identifier")
        with self._locked():
            run = self._load_unlocked(run_id)
            for task in run.tasks:
                if task.task_id != task_id:
                    continue
                task.status = status
                if output_path is not None:
                    task.output_path = output_path
                if record_count is not None:
                    task.record_count = record_count
                if error is not None:
                    task.error = error
                self._save_unlocked(run)
                return task
        raise KeyError("stored task was not found")

    def list_runs(self) -> list[StoredRun]:
        runs: list[StoredRun] = []
        with self._locked():
            for path in sorted(self.directory.glob("*.json")):
                try:
                    runs.append(self._load_unlocked(path.stem))
                except Exception:
                    raise ValueError("stored run repository is corrupt") from None
        return runs

    def recover_interrupted(self) -> list[StoredRun]:
        running = {
            TaskStatus.FETCHING,
            TaskStatus.EXPANDING,
            TaskStatus.PARSING,
            TaskStatus.RETRY_WAIT,
        }
        recovered: list[StoredRun] = []
        with self._locked():
            for path in sorted(self.directory.glob("*.json")):
                run = self._load_unlocked(path.stem)
                changed = False
                for task in run.tasks:
                    if task.status in running:
                        task.status = TaskStatus.PENDING
                        changed = True
                if changed:
                    self._save_unlocked(run)
                    recovered.append(run)
        return recovered

    def _run_path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must be a safe identifier")
        return self.directory / f"{run_id}.json"

    def _load_unlocked(self, run_id: str) -> StoredRun:
        try:
            payload = json.loads(
                self._run_path(run_id).read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict) or set(payload) != _RUN_FIELDS:
                raise ValueError("invalid stored run")
            if payload["schema_version"] != 1 or not isinstance(
                payload["tasks"], list
            ):
                raise ValueError("invalid stored run")
            tasks = []
            for item in payload["tasks"]:
                if not isinstance(item, dict) or set(item) != _TASK_FIELDS:
                    raise ValueError("invalid stored task")
                tasks.append(
                    StoredTask(**{**item, "status": TaskStatus(item["status"])})
                )
            run = StoredRun(payload["run_id"], tasks, payload["schema_version"])
            _validate_run(run, run_id)
            return run
        except (json.JSONDecodeError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError("stored run is corrupt") from exc

    def _save_unlocked(self, run: StoredRun) -> None:
        target = self._run_path(run.run_id)
        _validate_run(run, run.run_id)
        if target.exists():
            committed = self._load_unlocked(run.run_id)
            if _task_identity(committed) != _task_identity(run):
                raise TaskStoreConflictError(
                    "stored task identity cannot be changed"
                )
        payload = asdict(run)
        payload["tasks"] = [
            {**task, "status": task["status"].value}
            for task in payload["tasks"]
        ]
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{run.run_id}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    @contextmanager
    def _locked(self):
        with self._lock:
            with self._cross_process_lock():
                yield


def _validate_run(run: StoredRun, expected_run_id: str) -> None:
    if not isinstance(run, StoredRun) or run.run_id != expected_run_id:
        raise ValueError("stored run identity is invalid")
    if run.schema_version != 1 or not isinstance(run.tasks, list):
        raise ValueError("stored run schema is invalid")
    identities: set[str] = set()
    for task in run.tasks:
        if not isinstance(task, StoredTask):
            raise ValueError("stored task is invalid")
        if not isinstance(task.task_id, str) or not _TASK_ID.fullmatch(task.task_id):
            raise ValueError("stored task identity is invalid")
        if task.task_id in identities:
            raise ValueError("stored run contains duplicate task IDs")
        identities.add(task.task_id)
        if not isinstance(task.url, str) or not task.url:
            raise ValueError("stored task URL is invalid")
        if not isinstance(task.output_path, str):
            raise ValueError("stored task output path is invalid")
        if not isinstance(task.status, TaskStatus):
            raise ValueError("stored task status is invalid")
        if isinstance(task.record_count, bool) or not isinstance(task.record_count, int):
            raise ValueError("stored task record count is invalid")
        if not isinstance(task.error, str):
            raise ValueError("stored task error is invalid")


def _task_identity(run: StoredRun) -> dict[str, str]:
    return {task.task_id: task.url for task in run.tasks}


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
        raise OSError("task store lock creation failed")
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, _INFINITE)
        if result not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise OSError("task store lock acquisition failed")
        acquired = True
        yield
    finally:
        release_failed = acquired and not kernel32.ReleaseMutex(handle)
        close_failed = not kernel32.CloseHandle(handle)
        if release_failed or close_failed:
            raise OSError("task store lock release failed")
