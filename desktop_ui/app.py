"""Qt application lifecycle and desktop dependency assembly."""

from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import QApplication

from crawler.app_paths import AppPaths
from faculty_workflow.ai_settings import AiSettingsStore
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.providers import DeepSeekProvider
from faculty_workflow.service import WorkflowService

from .main_window import MainWindow
from .fixture import FixtureFacade
from .tokens import load_theme_qss
from .workflow_facade import WorkflowFacade


def build_workflow_facade() -> WorkflowFacade:
    """Assemble existing workflow services without exposing a saved API key to views."""
    paths = AppPaths.for_user()
    database = WorkflowDatabase(paths.root / "workflow" / "workflow.db")
    settings = AiSettingsStore(paths.settings / "workflow-ai")
    configuration, api_key = settings.load()
    provider = settings.build_provider(configuration, api_key)
    service = WorkflowService(database, provider=provider or DeepSeekProvider(api_key=""))
    facade = WorkflowFacade(service, database, settings, paths)
    facade.recover_interrupted_tasks()
    return facade


def _resolve_facade(
    facade: WorkflowFacade | FixtureFacade | None = None,
    *,
    fixture: bool = False,
) -> WorkflowFacade | FixtureFacade:
    """Resolve production or explicit in-memory acceptance data."""
    if facade is not None:
        return facade
    if fixture or os.environ.get("FACULTY_CRAWLER_UI_FIXTURE") == "1":
        return FixtureFacade()
    return build_workflow_facade()


def run_desktop(
    facade: WorkflowFacade | FixtureFacade | None = None,
    *,
    fixture: bool = False,
) -> int:
    """Start the native Qt shell and return Qt's standard event-loop exit code."""
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("教师目录采集器")
    application.setStyleSheet(load_theme_qss())
    window = MainWindow(_resolve_facade(facade, fixture=fixture))
    application.aboutToQuit.connect(window.shutdown)
    window.resize(1440, 900)
    window.show()
    return application.exec()
