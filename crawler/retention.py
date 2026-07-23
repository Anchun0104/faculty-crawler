from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from crawler.app_paths import AppPaths
from crawler.diagnostics import ReportRecord


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    path: Path
    created_at: datetime
    status: str


@dataclass(frozen=True)
class StorageUsage:
    bytes: int
    files: int

    @property
    def total_bytes(self) -> int:
        return self.bytes


class RetentionService:
    def __init__(
        self,
        paths: AppPaths,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.root = Path(paths.root).resolve()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def usage(self) -> StorageUsage:
        total_bytes = 0
        files = 0
        for directory in self._internal_directories():
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if path.is_file():
                    files += 1
                    total_bytes += path.stat().st_size
        return StorageUsage(total_bytes, files)

    def purge_due(
        self,
        reports: Iterable[ReportRecord],
        runs: Iterable[RunRecord],
        *,
        before_remove_run: Callable[[RunRecord], None] | None = None,
    ) -> list[Path]:
        now = self._now()
        removed: list[Path] = []
        for report in reports:
            if report.submitted_at is None:
                continue
            if now - _as_utc(report.submitted_at) < timedelta(days=30):
                continue
            removed.extend(self._remove_with_sidecar(report.path))
        for run in runs:
            if run.status.casefold() != "failed":
                continue
            if now - _as_utc(run.created_at) < timedelta(days=90):
                continue
            if before_remove_run is not None:
                before_remove_run(run)
            removed.extend(self._remove_with_sidecar(run.path))
        return removed

    def clear_temporary(self) -> list[Path]:
        removed: list[Path] = []
        for directory in self._internal_directories():
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.tmp")):
                removed.extend(self._remove_path(path))
        screenshots = Path(self.paths.screenshots)
        if screenshots.exists():
            for path in sorted(screenshots.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    removed.extend(self._remove_path(path))
        return removed

    def clear_internal_data(self, hostname: str | None = None) -> list[Path]:
        if hostname is not None:
            # SessionStore owns hostname hashing and validation; this operation
            # only removes its internal files when the caller supplies a safe key.
            if not isinstance(hostname, str) or not hostname.strip():
                raise ValueError("hostname must be non-empty")
            from crawler.session_store import _hostname_digest, _normalize_hostname

            digest = _hostname_digest(_normalize_hostname(hostname))
            return self._remove_matching(
                self.paths.sessions,
                (
                    f"{digest}.json",
                    f"{digest}.session",
                    f"{digest}.*.session",
                    f".{digest}.*.tmp",
                ),
            )
        removed: list[Path] = []
        for directory in (
            Path(self.paths.tasks),
            Path(self.paths.sessions),
            Path(self.paths.runs),
            Path(self.paths.logs),
        ):
            if directory.exists():
                for path in sorted(directory.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        removed.extend(self._remove_path(path))
        reports = Path(self.paths.reports)
        if reports.exists():
            for path in sorted(reports.rglob("*.zip.json")):
                removed.extend(self._remove_path(path))
        return removed

    def _remove_matching(self, directory: Path, patterns: tuple[str, ...]) -> list[Path]:
        removed: list[Path] = []
        for pattern in patterns:
            for path in sorted(directory.glob(pattern)):
                removed.extend(self._remove_path(path))
        return removed

    def _remove_with_sidecar(self, path: Path) -> list[Path]:
        removed = self._remove_path(path)
        sidecar = Path(path).with_suffix(Path(path).suffix + ".json")
        if sidecar.exists():
            removed.extend(self._remove_path(sidecar))
        return removed

    def _remove_path(self, path: Path) -> list[Path]:
        candidate = Path(path).absolute()
        target = candidate.resolve()
        try:
            target.relative_to(self.root)
            candidate.parent.resolve().relative_to(self.root)
        except ValueError:
            raise ValueError("retention target is outside AppPaths.root") from None
        if candidate.suffix.casefold() == ".xlsx":
            raise ValueError("retention cannot remove Excel output")
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink(missing_ok=True)
        elif candidate.is_dir():
            raise ValueError("retention target must be a file")
        else:
            return []
        return [candidate]

    def _internal_directories(self) -> tuple[Path, ...]:
        return (
            Path(self.paths.tasks),
            Path(self.paths.sessions),
            Path(self.paths.runs),
            Path(self.paths.logs),
            Path(self.paths.reports),
            Path(self.paths.screenshots),
        )

    def _now(self) -> datetime:
        return _as_utc(self._clock())


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
