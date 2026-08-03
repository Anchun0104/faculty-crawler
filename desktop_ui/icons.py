"""Qt-standard icon and label helpers used by the desktop shell."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QApplication, QStyle


@dataclass(frozen=True)
class NavigationItem:
    page_id: str
    label: str
    icon: QStyle.StandardPixmap


NAVIGATION_ITEMS = (
    NavigationItem("overview", "Overview", QStyle.SP_ComputerIcon),
    NavigationItem("tasks", "Tasks", QStyle.SP_FileDialogDetailedView),
    NavigationItem("verification", "Manual verification", QStyle.SP_DialogApplyButton),
    NavigationItem("runs", "Run history", QStyle.SP_BrowserReload),
    NavigationItem("sessions", "Site sessions", QStyle.SP_DriveNetIcon),
    NavigationItem("settings", "Settings", QStyle.SP_FileDialogContentsView),
)


def navigation_item(page_id: str) -> NavigationItem:
    """Return the semantic label and Qt-owned icon for a primary destination."""
    for item in NAVIGATION_ITEMS:
        if item.page_id == page_id:
            return item
    raise KeyError(f"Unknown navigation page: {page_id}")


def navigation_icon(page_id: str):
    """Resolve a native Qt standard icon after QApplication has been created."""
    item = navigation_item(page_id)
    return QApplication.style().standardIcon(item.icon)
