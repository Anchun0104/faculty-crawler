from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    tasks: Path
    sessions: Path
    runs: Path
    logs: Path
    reports: Path
    screenshots: Path
    settings: Path

    @classmethod
    def for_user(cls, base: Path | None = None) -> "AppPaths":
        root = base or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "FacultyCrawler"
        paths = cls(
            root,
            root / "tasks",
            root / "sessions",
            root / "runs",
            root / "logs",
            root / "reports",
            root / "screenshots",
            root / "settings",
        )
        for path in paths.__dict__.values():
            Path(path).mkdir(parents=True, exist_ok=True)
        return paths
