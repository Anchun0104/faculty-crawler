"""Settings container with compact category navigation and searchable AI section."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ai_settings import AiSettingsPage


class SettingsPage(QWidget):
    """Raycast-like settings framing; detailed sections are supplied incrementally."""

    _SECTIONS = (
        ("general", "常规"),
        ("crawl", "采集"),
        ("ai", "翻译与 AI"),
        ("storage", "存储与诊断"),
        ("about", "关于"),
    )

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._section_indexes: dict[str, int] = {}
        self._section_buttons: dict[str, QToolButton] = {}
        self._build()
        self.navigate("general")

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        nav = QFrame(self)
        nav.setObjectName("settingsNavigation")
        nav.setFixedWidth(220)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        nav_label = QLabel("设置", nav)
        nav_label.setObjectName("sectionHeading")
        nav_layout.addWidget(nav_label)
        self._buttons = QButtonGroup(self)
        self._buttons.setExclusive(True)
        for section_id, label in self._SECTIONS:
            button = QToolButton(nav)
            button.setText(label)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setAccessibleName(f"Open {label} settings")
            button.clicked.connect(lambda checked=False, target=section_id: self.navigate(target))
            self._buttons.addButton(button)
            self._section_buttons[section_id] = button
            nav_layout.addWidget(button)
        nav_layout.addStretch(1)
        layout.addWidget(nav)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        self.search_edit = QLineEdit(content)
        self.search_edit.setPlaceholderText("搜索设置")
        self.search_edit.setAccessibleName("Search settings")
        self.search_edit.textChanged.connect(self._search_sections)
        content_layout.addWidget(self.search_edit)
        self.section_stack = QStackedWidget(content)
        for section_id, label in self._SECTIONS:
            if section_id == "ai":
                self.ai_page = AiSettingsPage(self.facade, self.section_stack)
                page = self.ai_page
            else:
                page = self._placeholder_page(label)
            self._section_indexes[section_id] = self.section_stack.addWidget(page)
        content_layout.addWidget(self.section_stack, 1)
        layout.addWidget(content, 1)

    @staticmethod
    def _placeholder_page(label: str) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        title = QLabel(label, page)
        title.setObjectName("sectionHeading")
        page_layout.addWidget(title)
        copy = QLabel("此设置分组将在后续页面集成中提供。", page)
        copy.setWordWrap(True)
        page_layout.addWidget(copy)
        page_layout.addStretch(1)
        return page

    def navigate(self, section_id: str) -> None:
        try:
            index = self._section_indexes[section_id]
        except KeyError as error:
            raise ValueError(f"Unknown settings section: {section_id}") from error
        self.section_stack.setCurrentIndex(index)
        self._section_buttons[section_id].setChecked(True)
        if section_id == "ai":
            self.ai_page.refresh()

    def current_section(self) -> str:
        index = self.section_stack.currentIndex()
        return self._SECTIONS[index][0]

    def _search_sections(self, text: str) -> None:
        query = text.strip().casefold()
        if not query:
            return
        for section_id, label in self._SECTIONS:
            if query in label.casefold() or (query in {"ai", "api", "key", "模型", "密钥"} and section_id == "ai"):
                self.navigate(section_id)
                return
