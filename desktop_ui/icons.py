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
    NavigationItem("overview", "概览", QStyle.SP_ComputerIcon),
    NavigationItem("tasks", "任务", QStyle.SP_FileDialogDetailedView),
    NavigationItem("verification", "人工验证", QStyle.SP_DialogApplyButton),
    NavigationItem("runs", "运行历史", QStyle.SP_BrowserReload),
    NavigationItem("sessions", "站点会话", QStyle.SP_DriveNetIcon),
    NavigationItem("settings", "设置", QStyle.SP_FileDialogContentsView),
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
