from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import ReportView, RunView


class RunsPage(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_open_results: Callable[[RunView], None],
        on_generate_report: Callable[[RunView], None],
        on_handoff: Callable[[str], None],
        on_mark_submitted: Callable[[str], None],
    ) -> None:
        super().__init__(master, padding=(28, 24))
        self._runs: dict[str, RunView] = {}
        self._reports: dict[str, ReportView] = {}
        self._on_open_results = on_open_results
        self._on_generate_report = on_generate_report
        self._on_handoff = on_handoff
        self._on_mark_submitted = on_mark_submitted
        ttk.Label(self, text="运行记录", style="Heading.TLabel").pack(anchor=tk.W)

        run_table = ttk.Frame(self)
        run_table.pack(fill=tk.X, pady=(16, 8))
        self.run_tree = ttk.Treeview(run_table, columns=("summary", "folder"), show="tree headings", height=7, selectmode="browse")
        self.run_tree.heading("#0", text="批次")
        self.run_tree.heading("summary", text="结果摘要")
        self.run_tree.heading("folder", text="结果文件夹")
        self.run_tree.column("#0", width=190, minwidth=150)
        self.run_tree.column("summary", width=300, minwidth=180)
        self.run_tree.column("folder", width=360, minwidth=180)
        self.run_tree.pack(side=tk.TOP, fill=tk.X)
        run_horizontal = ttk.Scrollbar(
            run_table,
            orient=tk.HORIZONTAL,
            command=self.run_tree.xview,
        )
        run_horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        self.run_tree.configure(xscrollcommand=run_horizontal.set)
        run_actions = ttk.Frame(self)
        run_actions.pack(fill=tk.X)
        ttk.Button(run_actions, text="生成问题报告", command=self._generate, style="Primary.TButton").pack(side=tk.RIGHT)
        ttk.Button(run_actions, text="打开结果文件夹", command=self._open_results, style="Secondary.TButton").pack(side=tk.RIGHT, padx=(0, 8))

        ttk.Separator(self).pack(fill=tk.X, pady=18)
        ttk.Label(self, text="问题报告交接", style="Section.TLabel").pack(anchor=tk.W)
        report_table = ttk.Frame(self)
        report_table.pack(fill=tk.BOTH, expand=True, pady=(10, 8))
        self.report_tree = ttk.Treeview(report_table, columns=("created", "submitted", "path"), show="tree headings", height=6, selectmode="browse")
        self.report_tree.heading("#0", text="报告")
        self.report_tree.heading("created", text="生成时间")
        self.report_tree.heading("submitted", text="提交状态")
        self.report_tree.heading("path", text="本地 ZIP")
        self.report_tree.column("#0", width=160, minwidth=120)
        self.report_tree.column("created", width=180, minwidth=140)
        self.report_tree.column("submitted", width=120, minwidth=100)
        self.report_tree.column("path", width=410, minwidth=180)
        self.report_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        report_horizontal = ttk.Scrollbar(
            report_table,
            orient=tk.HORIZONTAL,
            command=self.report_tree.xview,
        )
        report_horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        self.report_tree.configure(xscrollcommand=report_horizontal.set)
        report_actions = ttk.Frame(self)
        report_actions.pack(fill=tk.X)
        ttk.Button(report_actions, text="标记为已提交", command=self._mark, style="Secondary.TButton").pack(side=tk.RIGHT)
        ttk.Button(report_actions, text="选择本地 ZIP 并打开飞书文件夹", command=self._handoff, style="Primary.TButton").pack(side=tk.RIGHT, padx=(0, 8))

    def set_records(self, runs: tuple[RunView, ...], reports: tuple[ReportView, ...]) -> None:
        self._runs = {record.run_id: record for record in runs}
        self.run_tree.delete(*self.run_tree.get_children())
        for record in runs:
            self.run_tree.insert("", tk.END, iid=record.run_id, text=record.run_id, values=(record.summary, record.result_folder))
        self._reports = {record.report_id: record for record in reports}
        self.report_tree.delete(*self.report_tree.get_children())
        for record in reports:
            submitted = record.submitted_at.astimezone().strftime("%Y-%m-%d") if record.submitted_at else "尚未标记"
            self.report_tree.insert("", tk.END, iid=record.report_id, text=record.report_id, values=(record.created_at.astimezone().strftime("%Y-%m-%d %H:%M"), submitted, record.path))

    def focus_primary(self) -> None:
        self.run_tree.focus_set()

    def _selected_run(self) -> RunView | None:
        selected = self.run_tree.selection()
        return self._runs.get(selected[0]) if selected else None

    def _selected_report(self) -> ReportView | None:
        selected = self.report_tree.selection()
        return self._reports.get(selected[0]) if selected else None

    def _open_results(self) -> None:
        if record := self._selected_run(): self._on_open_results(record)

    def _generate(self) -> None:
        if record := self._selected_run(): self._on_generate_report(record)

    def _handoff(self) -> None:
        if record := self._selected_report(): self._on_handoff(record.report_id)

    def _mark(self) -> None:
        if record := self._selected_report(): self._on_mark_submitted(record.report_id)
