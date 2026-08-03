"""Deterministic, in-memory data for real UI screenshot acceptance.

The fixture deliberately implements the small facade surface consumed by the
PySide6 pages.  It never opens the workflow database, network, AI provider or
browser; production startup does not use it unless explicitly opted in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from desktop_ui.models import AiSettingsView, AiUsageView, NewCrawlRequest, SaveAiSettings, UrlPreparation


class FixtureFacade:
    """Fixed rows and no-op commands used only for visual/interaction smoke tests."""

    def __init__(self) -> None:
        self.created_requests: list[NewCrawlRequest] = []
        self.cleared_hosts: list[str] = []
        self._ai_settings = AiSettingsView(
            enabled=True,
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            key_configured=True,
        )

    @staticmethod
    def _task_data() -> tuple[dict[str, object], ...]:
        return (
            {
                "id": "fixture-mit-eecs",
                "run_id": "run_20260731_140205",
                "name": "MIT EECS Faculty",
                "run_name": "MIT EECS Faculty",
                "discipline": "计算机科学",
                "status": "running",
                "source": "直接 URL",
                "created_at": "今天 14:02",
                "updated_at": "14:32",
                "schools": 1,
                "records": 86,
                "accepted": 86,
                "review": 7,
                "excluded": 31,
                "output_dir": r"D:\Faculty Results\mit-eecs-faculty.xlsx",
            },
            {
                "id": "fixture-stanford",
                "run_id": "run_20260731_141800",
                "name": "Stanford Computer Science",
                "run_name": "Stanford Computer Science",
                "discipline": "计算机科学",
                "status": "needs_verification",
                "source": "批量 XLSX",
                "created_at": "今天 14:18",
                "updated_at": "14:18",
                "schools": 1,
                "records": 0,
                "accepted": 0,
                "review": 0,
                "excluded": 0,
                "output_dir": r"D:\Faculty Results\stanford-cs.xlsx",
            },
            {
                "id": "fixture-oxford",
                "run_id": "run_20260731_133800",
                "name": "Oxford Physics",
                "run_name": "Oxford Physics",
                "discipline": "物理",
                "status": "completed",
                "source": "直接 URL",
                "created_at": "今天 13:38",
                "updated_at": "13:54",
                "schools": 1,
                "records": 128,
                "accepted": 128,
                "review": 4,
                "excluded": 12,
                "output_dir": r"D:\Faculty Results\oxford-physics.xlsx",
            },
            {
                "id": "fixture-eth",
                "run_id": "run_20260731_134100",
                "name": "ETH Zürich Biology",
                "run_name": "ETH Zürich Biology",
                "discipline": "生物学",
                "status": "queued",
                "source": "批量 XLSX",
                "created_at": "今天 13:41",
                "updated_at": "13:41",
                "schools": 1,
                "records": 0,
                "accepted": 0,
                "review": 0,
                "excluded": 0,
                "output_dir": r"D:\Faculty Results\eth-biology.xlsx",
            },
        )

    def task_rows(self, **_kwargs: object) -> tuple[dict[str, object], ...]:
        return tuple(dict(row) for row in self._task_data())

    def task_detail(self, task_id: str) -> dict[str, object]:
        for row in self._task_data():
            if row["id"] == task_id:
                return dict(row)
        return {"id": task_id, "status": "queued"}

    def run_detail(self, task_id: str) -> dict[str, object]:
        detail = self.task_detail(task_id)
        detail["timeline"] = self._timeline_for(str(task_id))
        return detail

    @staticmethod
    def _timeline_for(task_id: str) -> tuple[dict[str, str], ...]:
        if task_id == "fixture-mit-eecs":
            return (
                {"time": "14:02:05", "title": "任务已启动", "detail": "访问策略与输出目录检查通过。"},
                {"time": "14:02:13", "title": "目录页面已加载", "detail": "检测到 JavaScript 动态内容。"},
                {"time": "14:06:48", "title": "教师列表已枚举", "detail": "发现 128 个候选记录。"},
                {"time": "当前", "title": "正在解析个人主页", "detail": "86 / 128 · 同域串行访问。"},
            )
        return (
            {"time": "—", "title": "运行已完成", "detail": "已生成脱敏运行摘要。"},
        )

    def verification_rows(self, **_kwargs: object) -> tuple[dict[str, object], ...]:
        return (
            {
                "id": "fixture-review-stanford",
                "task_id": "fixture-stanford",
                "school": "Stanford Computer Science",
                "url": "https://cs.stanford.edu/people/faculty",
                "reason": "captcha",
                "status": "pending",
            },
            {
                "id": "fixture-review-toronto",
                "task_id": "fixture-stanford",
                "school": "University of Toronto Medicine",
                "url": "https://medicine.utoronto.ca/faculty",
                "reason": "login",
                "status": "pending",
            },
            {
                "id": "fixture-review-kyoto",
                "task_id": "fixture-stanford",
                "school": "京都大学 理学部",
                "url": "https://sci.kyoto-u.ac.jp/people",
                "reason": "challenge",
                "status": "pending",
            },
        )

    def session_rows(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "hostname": "cs.stanford.edu",
                "saved_at": "2026-07-22",
                "last_used_at": "今天 14:18",
                "expires_at": "29 天后",
                "days_remaining": 29,
            },
            {
                "hostname": "medicine.utoronto.ca",
                "saved_at": "2026-07-02",
                "last_used_at": "2026-07-18",
                "expires_at": "5 天后",
                "days_remaining": 5,
            },
            {
                "hostname": "sci.kyoto-u.ac.jp",
                "saved_at": "2026-07-28",
                "last_used_at": "昨天 17:42",
                "expires_at": "35 天后",
                "days_remaining": 35,
            },
        )

    def storage_summary(self) -> dict[str, int]:
        return {
            "bytes": 684 * 1024 * 1024,
            "files": 47,
            "snapshot_bytes": 438 * 1024 * 1024,
            "translation_cache_bytes": 164 * 1024 * 1024,
            "log_bytes": 72 * 1024 * 1024,
        }

    def ai_settings(self) -> AiSettingsView:
        return self._ai_settings

    def ai_usage(self) -> AiUsageView:
        return AiUsageView(128, 126, 2, 1_620_000, 220_000, 2.74)

    def ai_usage_details(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "created_at": "今天 14:29",
                "task_id": "fixture-mit-eecs",
                "operation": "translation",
                "model": "deepseek-v4-flash",
                "input_tokens": 18_200,
                "output_tokens": 2_400,
                "estimated_cost_usd": 0.42,
            },
            {
                "created_at": "今天 14:22",
                "task_id": "fixture-oxford",
                "operation": "classification",
                "model": "deepseek-v4-flash",
                "input_tokens": 12_800,
                "output_tokens": 1_960,
                "estimated_cost_usd": 0.31,
            },
            {
                "created_at": "今天 13:58",
                "task_id": "fixture-oxford",
                "operation": "extraction",
                "model": "deepseek-v4-pro",
                "input_tokens": 9_400,
                "output_tokens": 1_200,
                "estimated_cost_usd": 0.18,
            },
        )

    def save_ai_settings(self, settings: SaveAiSettings) -> None:
        self._ai_settings = AiSettingsView(
            enabled=settings.enabled,
            provider=settings.provider,
            base_url=settings.base_url,
            model=settings.model,
            key_configured=self._ai_settings.key_configured if settings.api_key is None else bool(settings.api_key),
        )

    def delete_ai_key(self) -> None:
        self._ai_settings = AiSettingsView(
            self._ai_settings.enabled,
            self._ai_settings.provider,
            self._ai_settings.base_url,
            self._ai_settings.model,
            False,
        )

    def test_ai_connection(self) -> None:
        return None

    def prepare_urls(self, raw: str) -> UrlPreparation:
        valid: list[str] = []
        duplicates: list[tuple[int, str]] = []
        invalid: list[tuple[int, str]] = []
        seen: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(), 1):
            value = line.strip()
            if not value:
                continue
            if not value.startswith(("http://", "https://")):
                invalid.append((line_number, value))
            elif value in seen:
                duplicates.append((line_number, value))
            else:
                seen.add(value)
                valid.append(value)
        return UrlPreparation(tuple(valid), tuple(duplicates), tuple(invalid))

    def prepare_schools_file(self, _path: str | Path) -> tuple[dict[str, str], ...]:
        return (
            {"school": "MIT", "directory_url": "https://eecs.mit.edu/faculty"},
            {"school": "Stanford", "directory_url": "https://cs.stanford.edu/people/faculty"},
        )

    def create_direct_tasks(self, request: NewCrawlRequest) -> str:
        self.created_requests.append(request)
        return "fixture-mit-eecs"

    def create_xlsx_task(self, _schools: tuple[object, ...], request: NewCrawlRequest) -> str:
        self.created_requests.append(request)
        return "fixture-mit-eecs"

    def run_task(self, _task_id: str, *, on_progress: Callable[[object], None] | None = None) -> dict[str, object]:
        if on_progress is not None:
            on_progress({"message": "fixture"})
        return {"status": "completed"}

    def export_task(self, _task_id: str) -> None:
        return None

    def clear_session(self, hostname: str) -> None:
        self.cleared_hosts.append(hostname)

    def clear_temporary_data(self) -> None:
        return None

    def clear_internal_data(self) -> None:
        return None

    def export_diagnostics(self) -> None:
        return None

    def begin_verification(self, _review_id: str) -> None:
        return None

    def finish_verification(self, _review_id: str) -> None:
        return None

    def defer_verification(self, _review_id: str) -> None:
        return None
