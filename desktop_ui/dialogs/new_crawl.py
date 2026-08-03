"""Task-source dialog for direct directory URLs and validated XLSX files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_ui.models import NewCrawlRequest, UrlPreparation
from desktop_ui.widgets.info_bar import InfoBar

if TYPE_CHECKING:
    from desktop_ui.workflow_facade import WorkflowFacade


class _LineNumberArea(QWidget):
    def __init__(self, editor: "LineNumberEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override name
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override name
        self.editor.paint_line_numbers(event)


class LineNumberEditor(QPlainTextEdit):
    """A plain-text URL editor with a lightweight, readable line gutter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

    def line_number_area_width(self) -> int:
        digits = max(1, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _blocks: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#F4F7FA"))
        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#667085"))
                painter.drawText(0, top, self._line_number_area.width() - 6, self.fontMetrics().height(), Qt.AlignRight, str(number))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1


class NewCrawlDialog(QDialog):
    """Create a crawl from newline-separated URLs or a validated XLSX source."""

    requested = Signal(object)
    xlsx_requested = Signal(str, object)

    def __init__(
        self,
        facade: WorkflowFacade,
        *,
        default_output_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.facade = facade
        self._mode = "urls"
        self._prepared_urls = UrlPreparation((), (), ())
        self._xlsx_path: Path | None = None
        self._xlsx_schools: tuple[object, ...] = ()
        self._xlsx_valid = False
        self._url_validation_timer = QTimer(self)
        self._url_validation_timer.setSingleShot(True)
        self._url_validation_timer.setInterval(125)
        self._url_validation_timer.timeout.connect(self._refresh_url_validation)
        self.setWindowTitle("新建采集")
        self.setMinimumWidth(680)
        self._build(default_output_dir or Path.cwd() / "workflow_output")
        self._refresh_url_validation()

    def _build(self, default_output_dir: Path) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        title = QLabel("新建采集", self)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        subtitle = QLabel("选择网址列表或学校 XLSX；AI 不会发现、猜测或替换目录网址。", self)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        mode_layout = QHBoxLayout()
        self.url_mode_button = QToolButton(self)
        self.url_mode_button.setText("直接粘贴 URL")
        self.url_mode_button.setCheckable(True)
        self.url_mode_button.setChecked(True)
        self.url_mode_button.clicked.connect(self.select_url_mode)
        mode_layout.addWidget(self.url_mode_button)
        self.xlsx_mode_button = QToolButton(self)
        self.xlsx_mode_button.setText("导入 XLSX")
        self.xlsx_mode_button.setCheckable(True)
        self.xlsx_mode_button.clicked.connect(self.select_xlsx_mode)
        mode_layout.addWidget(self.xlsx_mode_button)
        mode_layout.addStretch(1)
        layout.addLayout(mode_layout)

        self.source_stack = QStackedWidget(self)
        self.source_stack.addWidget(self._build_urls_page())
        self.source_stack.addWidget(self._build_xlsx_page())
        layout.addWidget(self.source_stack)

        details = QFormLayout()
        self.school_name_edit = QLineEdit(self)
        self.school_name_edit.setPlaceholderText("仅适用于单个 URL")
        self.school_name_edit.textChanged.connect(self._schedule_url_validation)
        details.addRow("学校名称（可选）", self.school_name_edit)
        self.discipline_edit = QLineEdit("General Faculty", self)
        details.addRow("学科", self.discipline_edit)
        self.output_dir_edit = QLineEdit(str(default_output_dir), self)
        self.output_dir_edit.textChanged.connect(self._refresh_batch_confirmation)
        output_row = QWidget(self)
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_dir_edit, 1)
        picker = QPushButton("选择", output_row)
        picker.clicked.connect(self._pick_output_dir)
        output_layout.addWidget(picker)
        details.addRow("输出目录", output_row)
        self.use_ai_checkbox = QCheckBox("仅对已获取页面使用已配置 AI", self)
        details.addRow("AI", self.use_ai_checkbox)
        layout.addLayout(details)

        self.summary_label = QLabel(self)
        self.summary_label.setObjectName("sourceSummary")
        self.validation_label = QLabel(self)
        self.validation_label.setObjectName("sourceValidation")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.validation_label)
        self.duplicate_details_button = QToolButton(self)
        self.duplicate_details_button.setText("查看重复 URL")
        self.duplicate_details_button.setCheckable(True)
        self.duplicate_details_button.toggled.connect(self._set_duplicate_details_visible)
        self.duplicate_details_label = QLabel(self)
        self.duplicate_details_label.setObjectName("duplicateUrlDetails")
        self.duplicate_details_label.setWordWrap(True)
        self.duplicate_details_button.hide()
        self.duplicate_details_label.hide()
        layout.addWidget(self.duplicate_details_button)
        layout.addWidget(self.duplicate_details_label)
        self.confirmation_label = QLabel(self)
        self.confirmation_label.setObjectName("batchConfirmation")
        self.confirmation_label.setWordWrap(True)
        layout.addWidget(self.confirmation_label)
        self.compliance_info = InfoBar(
            "请确认你有权访问这些公开页面，并遵守目标网站的服务条款与 robots 规则。",
            self,
        )
        layout.addWidget(self.compliance_info)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.start_button = QPushButton(self)
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)

    def _build_urls_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("目录 URL（每行一个）", page)
        layout.addWidget(label)
        self.url_editor = LineNumberEditor(page)
        self.url_editor.setAccessibleName("Directory URLs, one per line")
        self.url_editor.setPlaceholderText("https://university.edu/faculty\nhttps://school.edu/people")
        self.url_editor.setMinimumHeight(180)
        self.url_editor.textChanged.connect(self._schedule_url_validation)
        layout.addWidget(self.url_editor)
        return page

    def _build_xlsx_page(self) -> QWidget:
        page = QFrame(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("学校 XLSX（包含 school 和 directory_url 列）", page))
        row = QHBoxLayout()
        self.xlsx_path_edit = QLineEdit(page)
        self.xlsx_path_edit.setReadOnly(True)
        self.xlsx_path_edit.setAccessibleName("School XLSX path")
        row.addWidget(self.xlsx_path_edit, 1)
        picker = QPushButton("选择 XLSX", page)
        picker.clicked.connect(self._pick_xlsx_file)
        row.addWidget(picker)
        layout.addLayout(row)
        return page

    def select_url_mode(self) -> None:
        self._mode = "urls"
        self.source_stack.setCurrentIndex(0)
        self.url_mode_button.setChecked(True)
        self.xlsx_mode_button.setChecked(False)
        self.school_name_edit.setEnabled(True)
        self._refresh_url_validation()

    def select_xlsx_mode(self) -> None:
        self._url_validation_timer.stop()
        self._mode = "xlsx"
        self.source_stack.setCurrentIndex(1)
        self.url_mode_button.setChecked(False)
        self.xlsx_mode_button.setChecked(True)
        self.school_name_edit.setEnabled(False)
        self._refresh_xlsx_validation()

    def set_xlsx_path(self, path: str | Path) -> None:
        self._xlsx_path = Path(path)
        self.xlsx_path_edit.setText(str(self._xlsx_path))
        self._refresh_xlsx_validation()

    def _pick_xlsx_file(self) -> None:
        value, _filter = QFileDialog.getOpenFileName(self, "选择学校 XLSX", "", "Excel 工作簿 (*.xlsx)")
        if value:
            self.set_xlsx_path(value)

    def _pick_output_dir(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text())
        if value:
            self.output_dir_edit.setText(value)

    def _refresh_url_validation(self) -> None:
        if self._mode != "urls":
            return
        self._prepared_urls = self.facade.prepare_urls(self.url_editor.toPlainText())
        valid_count = len(self._prepared_urls.valid_urls)
        duplicate_count = len(self._prepared_urls.duplicate_lines)
        parts = [f"{valid_count} 个有效"]
        if duplicate_count:
            parts.append(f"{duplicate_count} 个重复已忽略")
        parts.append(f"将创建 1 个批次任务，包含 {valid_count} 所学校")
        self.summary_label.setText(" · ".join(parts))
        invalid_lines = [str(line) for line, _value in self._prepared_urls.invalid_lines]
        errors = [f"第 {'、'.join(invalid_lines)} 行 URL 无效"] if invalid_lines else []
        if valid_count > 1 and self.school_name_edit.text().strip():
            errors.append("学校名称仅可用于单个 URL")
        self.validation_label.setText("\n".join(errors))
        self._set_duplicate_details(self._prepared_urls.duplicate_lines)
        self._set_batch_confirmation(valid_count)
        self.start_button.setText(f"开始批次（{valid_count} 所学校）")
        self.start_button.setEnabled(self._prepared_urls.can_start and not errors)

    def _schedule_url_validation(self) -> None:
        if self._mode == "urls":
            self.start_button.setEnabled(False)
            self._url_validation_timer.start()

    def _set_duplicate_details(self, duplicates: tuple[tuple[int, str], ...]) -> None:
        self.duplicate_details_button.setVisible(bool(duplicates))
        self.duplicate_details_label.setText(
            "\n".join(f"第 {line} 行：{url}" for line, url in duplicates)
        )
        if not duplicates:
            self.duplicate_details_button.setChecked(False)
            self.duplicate_details_label.hide()

    def _set_duplicate_details_visible(self, visible: bool) -> None:
        self.duplicate_details_label.setVisible(visible and bool(self._prepared_urls.duplicate_lines))

    def _set_batch_confirmation(self, school_count: int) -> None:
        output_dir = self.output_dir_edit.text().strip() or "未选择输出目录"
        self.confirmation_label.setText(
            f"将创建 1 个批次任务，包含 {school_count} 所学校。输出目录：{output_dir}"
        )

    def _refresh_batch_confirmation(self, _value: str = "") -> None:
        school_count = (
            len(self._prepared_urls.valid_urls)
            if self._mode == "urls"
            else len(self._xlsx_schools)
        )
        self._set_batch_confirmation(school_count)

    def _refresh_xlsx_validation(self) -> None:
        if not self._xlsx_path:
            self._xlsx_valid = False
            self.summary_label.setText("尚未选择 XLSX 文件")
            self.validation_label.setText("")
            self.start_button.setText("开始采集")
            self.start_button.setEnabled(False)
            self._set_batch_confirmation(0)
            return
        try:
            schools = self.facade.prepare_schools_file(self._xlsx_path)
        except (OSError, ValueError) as error:
            self._xlsx_valid = False
            self.summary_label.setText("XLSX 未通过验证")
            self.validation_label.setText(str(error))
            self.start_button.setText("开始采集")
            self.start_button.setEnabled(False)
            self._set_batch_confirmation(0)
            return
        self._xlsx_valid = bool(schools)
        self._xlsx_schools = tuple(schools)
        self.summary_label.setText(f"{len(schools)} 所学校已验证 · 将创建 1 个批次任务，包含 {len(schools)} 所学校")
        self.validation_label.setText("")
        self._set_batch_confirmation(len(schools))
        self.start_button.setText(f"开始批次（{len(schools)} 所学校）")
        self.start_button.setEnabled(self._xlsx_valid)

    def _request(self) -> NewCrawlRequest:
        return NewCrawlRequest(
            urls=self._prepared_urls.valid_urls,
            output_dir=Path(self.output_dir_edit.text().strip()),
            school_name=self.school_name_edit.text().strip(),
            discipline=self.discipline_edit.text().strip() or "General Faculty",
            use_ai=self.use_ai_checkbox.isChecked(),
        )

    def _start(self) -> None:
        if self._mode == "urls":
            self._url_validation_timer.stop()
            self._refresh_url_validation()
            if not self._prepared_urls.can_start:
                return
            request = self._request()
            self.facade.create_direct_tasks(request)
            self.requested.emit(request)
            return
        if not self._xlsx_path or not self._xlsx_valid:
            return
        request = self._request()
        self.facade.create_xlsx_task(self._xlsx_schools, request)
        self.xlsx_requested.emit(str(self._xlsx_path), request)
