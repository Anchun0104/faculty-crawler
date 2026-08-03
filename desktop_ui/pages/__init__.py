"""Desktop UI pages."""

from .ai_settings import AiSettingsPage
from .settings import SettingsPage

__all__ = ("AiSettingsPage", "SettingsPage")
from .overview import OverviewPage
from .runs import RunsPage
from .sessions import SessionsPage
from .storage import StoragePage
from .tasks import TasksPage
from .verification import VerificationPage

__all__ = ("OverviewPage", "RunsPage", "SessionsPage", "StoragePage", "TasksPage", "VerificationPage")
