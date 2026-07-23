from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import VerificationView


class VerificationPage(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_start: Callable[[str, str], None],
        on_process_all: Callable[[], None],
        on_defer: Callable[[str, str], None],
        on_complete: Callable[[str, str], None],
    ) -> None:
        super().__init__(master, padding=(28, 24))
        self._records: dict[str, VerificationView] = {}
        self._on_start = on_start
        self._on_defer = on_defer
        self._on_complete = on_complete

        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 18))
        ttk.Label(header, text="人工验证", style="Heading.TLabel").pack(side=tk.LEFT)
        self.badge = ttk.Label(header, text="0 个待处理", style="Verification.TLabel")
        self.badge.pack(side=tk.LEFT, padx=(12, 0))
        self.process_all_button = ttk.Button(header, text="逐个处理全部任务", command=on_process_all, style="Verification.TButton")
        self.process_all_button.pack(side=tk.RIGHT)

        columns = ("site", "time", "reason", "status")
        table = ttk.Frame(self)
        table.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for name, title, width in (
            ("site", "站点", 240), ("time", "发现时间", 190), ("reason", "需要人工操作", 190), ("status", "状态", 150)
        ):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=100, stretch=name in {"site", "reason"})
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        horizontal = ttk.Scrollbar(
            table,
            orient=tk.HORIZONTAL,
            command=self.tree.xview,
        )
        horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.configure(xscrollcommand=horizontal.set)

        actions = ttk.Frame(self, padding=(0, 14, 0, 0))
        actions.pack(fill=tk.X)
        self.start_button = ttk.Button(actions, text="开始验证", command=self._start, style="Verification.TButton")
        self.start_button.pack(side=tk.RIGHT)
        self.complete_button = ttk.Button(actions, text="我已完成验证", command=self._complete, style="Primary.TButton", state=tk.DISABLED)
        self.complete_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.defer_button = ttk.Button(actions, text="暂不处理", command=self._defer, style="Secondary.TButton")
        self.defer_button.pack(side=tk.RIGHT, padx=(0, 8))

    def set_active(self, active: bool, *, role_busy: bool = False) -> None:
        self.complete_button.configure(
            state=tk.NORMAL if active and not role_busy else tk.DISABLED
        )
        available = not active and not role_busy
        self.start_button.configure(state=tk.NORMAL if available else tk.DISABLED)
        self.process_all_button.configure(
            state=tk.NORMAL if available else tk.DISABLED
        )
        self.defer_button.configure(
            state=tk.DISABLED if role_busy else tk.NORMAL
        )

    def set_records(self, records: tuple[VerificationView, ...], pending_count: int) -> None:
        self._records = {self._key(record): record for record in records}
        self.tree.delete(*self.tree.get_children())
        for record in records:
            self.tree.insert("", tk.END, iid=self._key(record), values=(record.hostname, record.detected_at, record.reason, record.status_text))
        self.badge.configure(text=f"{pending_count} 个待处理")
        if records:
            key = self._key(records[0])
            self.tree.selection_set(key)
            self.tree.focus(key)

    def focus_primary(self) -> None:
        self.tree.focus_set()

    @staticmethod
    def _key(record: VerificationView) -> str:
        return f"{record.run_id}\x1f{record.task_id}"

    def _selected(self) -> VerificationView | None:
        selected = self.tree.selection()
        return self._records.get(selected[0]) if selected else None

    def _start(self) -> None:
        if record := self._selected():
            self._on_start(record.run_id, record.task_id)

    def _defer(self) -> None:
        if record := self._selected():
            self._on_defer(record.run_id, record.task_id)

    def _complete(self) -> None:
        if record := self._selected():
            self._on_complete(record.run_id, record.task_id)
