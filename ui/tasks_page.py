from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import TaskView


class TasksPage(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_action: Callable[[TaskView], None],
        on_open_result: Callable[[TaskView], None],
        on_stop: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=(28, 24))
        self._records: dict[str, TaskView] = {}
        self._on_action = on_action
        self._on_open_result = on_open_result

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 18))
        ttk.Label(header, text="当前任务", style="Heading.TLabel").pack(side=tk.LEFT)
        ttk.Button(
            header,
            text="完成当前网址后停止",
            command=on_stop,
            style="Secondary.TButton",
        ).pack(side=tk.RIGHT)

        columns = ("track", "site", "status", "records", "file", "next")
        table = ttk.Frame(self)
        table.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            style="Task.Treeview",
            selectmode="browse",
        )
        headings = {
            "track": "",
            "site": "站点 / 安全网址",
            "status": "状态",
            "records": "数量",
            "file": "结果文件",
            "next": "下一步",
        }
        widths = {"track": 38, "site": 300, "status": 120, "records": 64, "file": 190, "next": 130}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], minwidth=widths[name], stretch=name in {"site", "file"})
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        horizontal = ttk.Scrollbar(
            table,
            orient=tk.HORIZONTAL,
            command=self.tree.xview,
        )
        horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.bind("<Double-1>", lambda _event: self._invoke_action())
        self.tree.bind("<Return>", lambda _event: self._invoke_action())
        self.tree.bind("<<TreeviewSelect>>", self._refresh_details)

        actions = ttk.Frame(self, padding=(0, 12, 0, 10))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="执行下一步", command=self._invoke_action, style="Primary.TButton").pack(side=tk.RIGHT)
        ttk.Button(actions, text="打开结果文件夹", command=self._open_result, style="Secondary.TButton").pack(side=tk.RIGHT, padx=(0, 8))

        detail_header = ttk.Frame(self)
        detail_header.pack(fill=tk.X)
        self.detail_button = ttk.Button(
            detail_header,
            text="查看技术信息",
            command=self.toggle_details,
            style="Secondary.TButton",
        )
        self.detail_button.pack(side=tk.LEFT)
        self.detail_text = tk.StringVar(value="")
        self.detail_label = ttk.Label(self, textvariable=self.detail_text, style="Technical.TLabel", wraplength=760)
        self._details_visible = False

    def set_records(self, records: tuple[TaskView, ...]) -> None:
        selected = self.tree.selection()
        selected_key = selected[0] if selected else ""
        self._records = {record.key: record for record in records}
        self.tree.delete(*self.tree.get_children())
        for record in records:
            self.tree.insert(
                "",
                tk.END,
                iid=record.key,
                values=(
                    f"│ {record.status_symbol}",
                    f"{record.site}\n{record.safe_url}",
                    record.status_text,
                    record.record_count or "",
                    record.output_name,
                    record.next_action,
                ),
            )
        if records:
            key = selected_key if selected_key in self._records else records[0].key
            self.tree.selection_set(key)
            self.tree.focus(key)
        self._refresh_details()

    def focus_primary(self) -> None:
        self.tree.focus_set()

    def _selected(self) -> TaskView | None:
        selected = self.tree.selection()
        return self._records.get(selected[0]) if selected else None

    def _invoke_action(self) -> None:
        if record := self._selected():
            self._on_action(record)

    def _open_result(self) -> None:
        if record := self._selected():
            self._on_open_result(record)

    def toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        if self._details_visible:
            self._refresh_details()
            self.detail_label.pack(fill=tk.X, pady=(8, 0))
            self.detail_button.configure(text="收起技术信息")
        else:
            self.detail_label.pack_forget()
            self.detail_button.configure(text="查看技术信息")

    def _refresh_details(self, _event=None) -> None:
        if not self._details_visible:
            return
        record = self._selected()
        self.detail_text.set(
            record.technical_info
            if record and record.technical_info
            else "没有可显示的技术信息。"
        )
