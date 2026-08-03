"""Manual-only verification queue. No CAPTCHA bypassing is offered or implied."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from desktop_ui.widgets.data_table import DataTable
from desktop_ui.widgets.empty_state import EmptyState
from desktop_ui.widgets.info_bar import InfoBar
from desktop_ui.widgets.page_header import PageHeader


class VerificationPage(QWidget):
    """Two-pane workflow: queue on the left, selected manual site on the right."""

    start_requested = Signal(str)
    defer_requested = Signal(str)
    complete_requested = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._selected = ""
        self._rows: dict[str, dict[str, object]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.page_header = PageHeader("人工验证", "等待用户在可见浏览器中完成合法验证。", "逐个处理全部", self)
        layout.addWidget(self.page_header)
        self.info_bar = InfoBar(
            "人工验证使用可见浏览器；不会自动破解 CAPTCHA、绕过访问控制或跨站点复用会话。",
            self,
        )
        layout.addWidget(self.info_bar)

        panes = QHBoxLayout()
        panes.setSpacing(12)
        self.table = DataTable(("学校", "原因", "URL"), self)
        self.table.setAccessibleName("人工验证队列")
        self.table.selection_changed.connect(self.select_review)
        self.empty_state = EmptyState("暂无人工验证", "被拦截或要求登录的站点会显示在这里。", parent=self)
        queue = QWidget(self)
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.addWidget(self.table, 1)
        queue_layout.addWidget(self.empty_state, 1)
        panes.addWidget(queue, 1)
        panes.addWidget(self._build_selected_site_pane())
        layout.addLayout(panes, 1)
        self.refresh()

    def _build_selected_site_pane(self) -> QFrame:
        pane = QFrame(self)
        pane.setObjectName("verificationInspector")
        pane.setFixedWidth(360)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 16, 16, 16)
        heading = QLabel("所选站点", pane)
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)
        self.selected_site_label = QLabel("请选择一个站点继续", pane)
        self.selected_site_label.setWordWrap(True)
        layout.addWidget(self.selected_site_label)
        self.mock_browser = self._build_mock_browser(pane)
        layout.addWidget(self.mock_browser)
        self.browser_status_label = QLabel("可见浏览器：尚未启动", pane)
        self.browser_status_label.setObjectName("settingRowHint")
        self.browser_status_label.setWordWrap(True)
        layout.addWidget(self.browser_status_label)
        self.instructions_label = QLabel(
            "1. 打开可见浏览器。\n"
            "2. 在浏览器中自行完成登录或验证。\n"
            "3. 返回应用标记完成，或暂不处理。",
            pane,
        )
        self.instructions_label.setWordWrap(True)
        layout.addWidget(self.instructions_label)
        layout.addStretch(1)
        self.start_button = QPushButton("开始验证", pane)
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self._selected))
        self.defer_button = QPushButton("暂不处理", pane)
        self.defer_button.clicked.connect(lambda: self.defer_requested.emit(self._selected))
        self.complete_button = QPushButton("标记完成", pane)
        self.complete_button.clicked.connect(lambda: self.complete_requested.emit(self._selected))
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(False)
            layout.addWidget(button)
        return pane

    @staticmethod
    def _build_mock_browser(parent: QWidget) -> QFrame:
        browser = QFrame(parent)
        browser.setObjectName("mockBrowserCard")
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(10, 8, 10, 8)
        address = QLabel("🔒 可见浏览器预览", browser)
        address.setObjectName("browserAddress")
        browser_layout.addWidget(address)
        body = QLabel("完成验证后返回此处继续。", browser)
        body.setObjectName("browserBody")
        body.setWordWrap(True)
        browser_layout.addWidget(body)
        return browser

    def refresh(self) -> None:
        rows = self.facade.verification_rows() if hasattr(self.facade, "verification_rows") else ()
        self._rows = {str(row["id"]): dict(row) for row in rows}
        if self._selected not in self._rows:
            self._clear_selection()
        self.table.set_rows(
            (str(row["id"]), (row["school"], self._reason_text(row["reason"]), row["url"]))
            for row in rows
        )
        self.table.setVisible(bool(rows))
        self.empty_state.setVisible(not rows)

    def select_review(self, review_id: str) -> None:
        row = self._rows.get(review_id)
        if row is None:
            self._clear_selection()
            return
        self._selected = review_id
        self.selected_site_label.setText(f"{row['school']}\n{row['url']}")
        self.browser_status_label.setText("可见浏览器：准备启动")
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(True)

    def _clear_selection(self) -> None:
        self._selected = ""
        self.selected_site_label.setText("请选择一个站点继续")
        self.browser_status_label.setText("可见浏览器：尚未启动")
        for button in (self.start_button, self.defer_button, self.complete_button):
            button.setEnabled(False)

    @staticmethod
    def _reason_text(reason: object) -> str:
        return {
            "challenge": "访问验证",
            "captcha": "CAPTCHA 验证",
            "login": "需要登录",
        }.get(str(reason), str(reason))
