"""The reusable native-window shell for Faculty Crawler."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import NAVIGATION_ITEMS, navigation_icon
from .pages.settings import SettingsPage
from .pages.overview import OverviewPage
from .pages.tasks import TasksPage
from .pages.verification import VerificationPage
from .pages.runs import RunsPage
from .pages.sessions import SessionsPage
from .tokens import LIGHT_TOKENS
from .widgets.status_badge import BackgroundStatus, StatusBadge


class MainWindow(QMainWindow):
    """Native Qt main window with grouped, keyboard-accessible navigation."""

    _PAGE_IDS = tuple(item.page_id for item in NAVIGATION_ITEMS)
    _NAVIGATION_COLLAPSE_BREAKPOINT = 1280
    _GROUPS = (
        ("Work", ("overview", "tasks", "verification")),
        ("Records", ("runs", "sessions")),
        ("System", ("settings",)),
    )

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._nav_collapsed = False
        self._page_index: dict[str, int] = {}
        self._navigation_buttons: dict[str, QToolButton] = {}
        self._group_labels: list[QLabel] = []
        self._build_shell()
        self._settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self)
        self._settings_shortcut.setContext(Qt.WindowShortcut)
        self._settings_shortcut.activated.connect(lambda: self.navigate("settings"))
        self.navigate("overview")

    def _build_shell(self) -> None:
        self.setWindowTitle("Faculty Crawler")
        self.setMinimumSize(1180, 720)

        root = QWidget(self)
        root.setObjectName("appShell")
        root.setAccessibleName("Faculty Crawler application")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_navigation())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

    def _build_navigation(self) -> QFrame:
        self._navigation = QFrame(self)
        self._navigation.setObjectName("primaryNavigation")
        self._navigation.setAccessibleName("Primary navigation")
        self._navigation.setFixedWidth(LIGHT_TOKENS.nav_expanded)
        layout = QVBoxLayout(self._navigation)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._nav_title = QLabel("Faculty Crawler", self._navigation)
        self._nav_title.setObjectName("navigationProductName")
        self._nav_title.setAccessibleName("Faculty Crawler")
        header.addWidget(self._nav_title, 1)
        self.navigation_toggle = QToolButton(self._navigation)
        self.navigation_toggle.setText("☰")
        self.navigation_toggle.setCheckable(True)
        self.navigation_toggle.setAccessibleName("Collapse navigation")
        self.navigation_toggle.setToolTip("Collapse navigation")
        self.navigation_toggle.toggled.connect(self.set_navigation_collapsed)
        header.addWidget(self.navigation_toggle)
        layout.addLayout(header)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        items = {item.page_id: item for item in NAVIGATION_ITEMS}
        for group_label, page_ids in self._GROUPS:
            label = QLabel(group_label, self._navigation)
            label.setObjectName("navigationGroup")
            self._group_labels.append(label)
            layout.addWidget(label)
            for page_id in page_ids:
                item = items[page_id]
                button = QToolButton(self._navigation)
                button.setObjectName(f"navigation_{page_id}")
                button.setCheckable(True)
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                button.setIcon(navigation_icon(page_id))
                button.setText(item.label)
                button.setAccessibleName(f"Navigate to {item.label}")
                button.setToolTip(item.label)
                button.clicked.connect(lambda checked=False, target=page_id: self.navigate(target))
                self._button_group.addButton(button)
                self._navigation_buttons[page_id] = button
                layout.addWidget(button)
        layout.addStretch(1)
        self.background_status = StatusBadge(parent=self._navigation)
        layout.addWidget(self.background_status)
        return self._navigation

    def _build_content(self) -> QFrame:
        content = QFrame(self)
        content.setObjectName("contentSurface")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(16)
        title = QLabel("Faculty Crawler", content)
        title.setObjectName("shellTitle")
        title.setAccessibleName("Application title")
        layout.addWidget(title)
        self.page_stack = QStackedWidget(content)
        self.page_stack.setAccessibleName("Main content")
        for item in NAVIGATION_ITEMS:
            page = self._build_page(item.page_id, item.label)
            page.setObjectName(f"page_{item.page_id}")
            page.setAccessibleName(f"{item.label} page")
            self._page_index[item.page_id] = self.page_stack.addWidget(page)
        layout.addWidget(self.page_stack, 1)
        return content

    def _build_page(self, page_id: str, label: str) -> QWidget:
        page_types = {
            "overview": OverviewPage,
            "tasks": TasksPage,
            "verification": VerificationPage,
            "runs": RunsPage,
            "sessions": SessionsPage,
        }
        if page_id == "settings":
            self.settings_page = SettingsPage(self.facade, self.page_stack)
            return self.settings_page
        if page_id in page_types:
            page = page_types[page_id](self.facade, self.page_stack)
            setattr(self, f"{page_id}_page", page)
            return page
        page = QWidget(self.page_stack)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(label, page)
        heading.setObjectName("pageHeading")
        page_layout.addWidget(heading)
        page_layout.addStretch(1)
        return page

    def page_ids(self) -> tuple[str, ...]:
        return self._PAGE_IDS

    def current_page_id(self) -> str:
        index = self.page_stack.currentIndex()
        return self._PAGE_IDS[index]

    def navigate(self, page_id: str) -> None:
        try:
            index = self._page_index[page_id]
        except KeyError as error:
            raise ValueError(f"Unknown page_id: {page_id}") from error
        self.page_stack.setCurrentIndex(index)
        self._navigation_buttons[page_id].setChecked(True)

    def navigation_button(self, page_id: str) -> QToolButton:
        return self._navigation_buttons[page_id]

    def navigation_buttons(self) -> Iterable[QToolButton]:
        return tuple(self._navigation_buttons.values())

    def set_navigation_collapsed(self, collapsed: bool) -> None:
        self._nav_collapsed = bool(collapsed)
        width = LIGHT_TOKENS.nav_collapsed if self._nav_collapsed else LIGHT_TOKENS.nav_expanded
        self._navigation.setFixedWidth(width)
        self._nav_title.setVisible(not self._nav_collapsed)
        for label in self._group_labels:
            label.setVisible(not self._nav_collapsed)
        self.background_status.set_compact(self._nav_collapsed)
        with QSignalBlocker(self.navigation_toggle):
            self.navigation_toggle.setChecked(self._nav_collapsed)
        self.navigation_toggle.setText("☰" if not self._nav_collapsed else "›")
        self.navigation_toggle.setAccessibleName(
            "Expand navigation" if self._nav_collapsed else "Collapse navigation"
        )
        self.navigation_toggle.setToolTip(self.navigation_toggle.accessibleName())
        style = Qt.ToolButtonIconOnly if self._nav_collapsed else Qt.ToolButtonTextBesideIcon
        for button in self._navigation_buttons.values():
            button.setToolButtonStyle(style)

    def is_navigation_collapsed(self) -> bool:
        return self._nav_collapsed

    def navigation_width(self) -> int:
        return self._navigation.width()

    @classmethod
    def navigation_breakpoint(cls) -> int:
        """Return the supported-width breakpoint for automatic nav collapse."""
        return cls._NAVIGATION_COLLAPSE_BREAKPOINT

    def navigation_group_labels(self) -> tuple[QLabel, ...]:
        return tuple(self._group_labels)

    def set_background_status(self, status: BackgroundStatus) -> None:
        self.background_status.set_status(status)

    def background_status_text(self) -> str:
        return self.background_status.status_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        super().resizeEvent(event)
        self.set_navigation_collapsed(self.width() < self.navigation_breakpoint())
