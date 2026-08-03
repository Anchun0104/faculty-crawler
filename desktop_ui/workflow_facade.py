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
