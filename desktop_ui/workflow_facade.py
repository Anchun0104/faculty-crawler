"""Framework-independent application operations for the desktop UI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from crawler.app_paths import AppPaths
from faculty_workflow.ai_settings import AiSettingsStore, ProviderConfiguration
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.importers import load_schools
from faculty_workflow.models import SchoolInput, normalize_url

from .models import AiSettingsView, AiUsageView, NewCrawlRequest, SaveAiSettings, UrlPreparation

if TYPE_CHECKING:
    from faculty_workflow.service import WorkflowService


class WorkflowFacade:
    def __init__(
        self,
        service: WorkflowService,
        database: WorkflowDatabase,
        ai_settings_store: AiSettingsStore,
        app_paths: AppPaths,
    ) -> None:
        self.service = service
        self.database = database
        self.ai_settings_store = ai_settings_store
        self.app_paths = app_paths

    def prepare_urls(self, raw: str) -> UrlPreparation:
        valid_urls: list[str] = []
        duplicate_lines: list[tuple[int, str]] = []
        invalid_lines: list[tuple[int, str]] = []
        known_urls: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(), start=1):
            value = line.strip()
            if not value:
                continue
            normalized = normalize_url(value)
            if not normalized:
                invalid_lines.append((line_number, value))
            elif normalized in known_urls:
                duplicate_lines.append((line_number, normalized))
            else:
                known_urls.add(normalized)
                valid_urls.append(normalized)
        return UrlPreparation(tuple(valid_urls), tuple(duplicate_lines), tuple(invalid_lines))

    def create_direct_tasks(self, request: NewCrawlRequest) -> str:
        prepared = self.prepare_urls("\n".join(request.urls))
        if not prepared.can_start:
            raise ValueError("Provide at least one valid URL and correct invalid URL lines")
        return self.service.create_direct_url_task(
            directory_urls=prepared.valid_urls,
            output_dir=request.output_dir,
            school_name=request.school_name,
            discipline=request.discipline,
            use_ai=request.use_ai,
            routine_model=request.routine_model,
            escalation_model=request.escalation_model,
            budget_usd=request.budget_usd,
        )

    def prepare_schools_file(self, path: str | Path) -> tuple[SchoolInput, ...]:
        """Validate an XLSX source with the workflow's established importer."""
        source = Path(path)
        if source.suffix.casefold() != ".xlsx":
            raise ValueError("请选择 XLSX 文件")
        return tuple(load_schools(source))

    def create_xlsx_task(
        self,
        schools: tuple[SchoolInput, ...],
        request: NewCrawlRequest,
    ) -> str:
        """Create a task from the exact school rows validated by the XLSX picker."""
        if not schools:
            raise ValueError("XLSX 文件中没有可采集的学校")
        return self.service.create_task_from_schools(
            schools=schools,
            discipline=request.discipline,
            output_dir=request.output_dir,
            budget_usd=request.budget_usd,
            generate_ai_policy=request.use_ai,
            routine_model=request.routine_model,
            escalation_model=request.escalation_model,
        )

    def ai_settings(self) -> AiSettingsView:
        configuration = self.ai_settings_store.load_configuration()
        return self._ai_settings_view(configuration)

    def save_ai_settings(self, command: SaveAiSettings) -> AiSettingsView:
        configuration = self._configuration_from(command)
        self.ai_settings_store.save(configuration, command.api_key)
        return self._ai_settings_view(configuration)

    def delete_ai_key(self) -> AiSettingsView:
        """Explicitly remove the key and return to a safe local-only state."""
        # Disable the provider before deleting its credential.  This prevents a
        # saved-but-unconfigured provider state that would fail when a task is
        # started, while keeping plaintext entirely inside the settings layer.
        self.ai_settings_store.save(ProviderConfiguration.local(), None)
        self.ai_settings_store.delete_key()
        return self.ai_settings()

    def test_ai_connection(self) -> object:
        """Test the saved configuration internally; the decrypted key never leaves this layer."""
        configuration = self.ai_settings_store.load_configuration()
        api_key = self.ai_settings_store.keys.load()
        return self.ai_settings_store.test_connection(configuration, api_key)

    def ai_usage(self) -> AiUsageView:
        """Return the current UTC month's recorded AI usage for the settings UI."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        row = self.database.ai_usage_summary(since=month_start)
        return AiUsageView(
            calls=int(row["calls"]),
            succeeded=int(row["succeeded"]),
            failed=int(row["failed"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            estimated_cost_usd=float(row["estimated_cost_usd"]),
        )

    def ai_usage_details(self, *, limit: int = 200) -> tuple[dict[str, object], ...]:
        """Return display-safe call metadata for the settings table.

        Provider response IDs and errors are intentionally omitted: they can be
        sensitive and are not needed for an operator to review usage.
        """
        rows = self.database.list_ai_usage(task_id=None, limit=limit)
        return tuple(
            {
                "created_at": str(row["created_at"]),
                "task_id": str(row["task_id"]),
                "operation": str(row["operation"]),
                "model": str(row["model"]),
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "estimated_cost_usd": float(row["estimated_cost_usd"]),
                "status": str(row["status"]),
            }
            for row in rows
        )

    def task_rows(self, *, limit: int = 200) -> tuple[dict[str, object], ...]:
        """Safe task list for the desktop UI; filesystem and SQLite stay behind the facade."""
        return tuple(self._task_row(row) for row in self.database.list_tasks(limit=limit))

    def task_detail(self, task_id: str) -> dict[str, object]:
        task = self.database.summary(task_id)
        return {
            "id": str(task["id"]), "discipline": str(task["discipline"]),
            "status": str(task["status"]), "output_dir": str(task["output_dir"]),
            "created_at": str(task["created_at"]), "updated_at": str(task["updated_at"]),
            "schools": sum(int(value) for value in task["schools"].values()),
            "records": sum(int(value) for value in task["candidates"].values()),
            "spent_usd": float(task["spent_usd"]), "budget_usd": float(task["budget_usd"]),
            "warning": str(task["warning"]), "error": str(task["error"]),
        }

    def verification_rows(self, *, limit: int = 200) -> tuple[dict[str, object], ...]:
        return tuple({
            "id": str(row["id"]), "task_id": str(row["task_id"]), "school": str(row["school"]),
            "url": str(row["url"]), "reason": str(row["reason"]), "status": str(row["status"]),
        } for row in self.database.list_pending_access_reviews(limit=limit))

    def resolve_verification(self, review_id: str, *, retry: bool) -> None:
        self.database.resolve_access_review(int(review_id), retry=retry)

    def begin_verification(self, review_id: str) -> None:
        """Launch the existing visible-browser verification flow off the GUI thread."""
        self.service.begin_access_verification(int(review_id))

    def finish_verification(self, review_id: str) -> None:
        """Persist a user-completed verification; no CAPTCHA automation is involved."""
        self.service.finish_access_verification(int(review_id))

    def run_task(self, task_id: str, *, on_progress=None) -> dict[str, object]:
        """Run the established batch workflow; callers must invoke this from a worker."""
        return dict(self.service.run_task(task_id, on_progress=on_progress))

    def session_rows(self) -> tuple[dict[str, object], ...]:
        store = getattr(getattr(self.service, "fetcher", None), "session_store", None)
        if store is None or not hasattr(store, "list"):
            return ()
        return tuple({"hostname": str(item.hostname), "saved_at": str(item.saved_at),
                      "expires_at": str(item.expires_at)} for item in store.list())

    def clear_session(self, hostname: str) -> None:
        store = getattr(getattr(self.service, "fetcher", None), "session_store", None)
        if store is None or not hasattr(store, "clear"):
            raise RuntimeError("Site session storage is unavailable")
        store.clear(hostname)

    def storage_summary(self) -> dict[str, object]:
        """Minimal, display-safe storage status. Detailed cleanup remains an explicit command."""
        from crawler.retention import RetentionService
        usage = RetentionService(self.app_paths).usage()
        return {"bytes": usage.bytes, "files": usage.files}

    @staticmethod
    def _task_row(row: object) -> dict[str, object]:
        return {"id": str(row["id"]), "discipline": str(row["discipline"]),
                "status": str(row["status"]), "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]), "output_dir": str(row["output_dir"])}

    def _ai_settings_view(self, configuration: ProviderConfiguration) -> AiSettingsView:
        return AiSettingsView(
            enabled=configuration.enabled,
            provider=configuration.provider,
            base_url=configuration.base_url,
            model=configuration.model,
            key_configured=self.ai_settings_store.key_configured(),
        )

    @staticmethod
    def _configuration_from(command: SaveAiSettings) -> ProviderConfiguration:
        if not command.enabled:
            return ProviderConfiguration.local()
        if command.provider == "deepseek" and not command.base_url.strip():
            return ProviderConfiguration.deepseek(model=command.model)
        return ProviderConfiguration(
            enabled=True,
            provider=command.provider,
            base_url=command.base_url,
            model=command.model,
        )
