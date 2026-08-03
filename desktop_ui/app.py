"""Qt application lifecycle and desktop dependency assembly."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from crawler.app_paths import AppPaths
from faculty_workflow.ai_settings import AiSettingsStore
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.providers import DeepSeekProvider
from faculty_workflow.service import WorkflowService

from .main_window import MainWindow
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
    return WorkflowFacade(service, database, settings, paths)


def run_desktop(facade: WorkflowFacade | None = None) -> int:
    """Start the native Qt shell and return Qt's standard event-loop exit code."""
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Faculty Crawler")
    application.setStyleSheet(load_theme_qss())
    window = MainWindow(facade or build_workflow_facade())
    application.aboutToQuit.connect(window.shutdown)
    window.resize(1440, 900)
    window.show()
    return application.exec()
