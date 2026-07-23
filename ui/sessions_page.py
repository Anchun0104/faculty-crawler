from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import SessionView


class SessionsPage(ttk.Frame):
    def __init__(self, master, *, on_clear: Callable[[str], None], on_clear_all: Callable[[], None]) -> None:
        super().__init__(master, padding=(28, 24))
        self._records: dict[str, SessionView] = {}
        self._on_clear = on_clear
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 18))
        ttk.Label(header, text="保存的会话", style="Heading.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="清除全部会话", command=on_clear_all, style="Destructive.TButton").pack(side=tk.RIGHT)

        columns = ("host", "saved", "used", "cleanup")
        table = ttk.Frame(self)
        table.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for name, title, width in (
            ("host", "站点", 240), ("saved", "保存时间", 190), ("used", "最近使用", 190), ("cleanup", "计划清理", 190)
        ):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=120, stretch=name == "host")
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        horizontal = ttk.Scrollbar(
            table,
            orient=tk.HORIZONTAL,
            command=self.tree.xview,
        )
        horizontal.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.configure(xscrollcommand=horizontal.set)
        ttk.Button(self, text="清除此站点会话", command=self._clear, style="Destructive.TButton").pack(anchor=tk.E, pady=(14, 0))

    def set_records(self, records: tuple[SessionView, ...]) -> None:
        self._records = {record.hostname: record for record in records}
        self.tree.delete(*self.tree.get_children())
        for record in records:
            self.tree.insert("", tk.END, iid=record.hostname, values=(record.hostname, _date(record.saved_at), _date(record.last_used_at), _date(record.cleanup_at)))
        if records:
            self.tree.selection_set(records[0].hostname)

    def focus_primary(self) -> None:
        self.tree.focus_set()

    def _clear(self) -> None:
        selected = self.tree.selection()
        if selected:
            self._on_clear(self._records[selected[0]].hostname)


def _date(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")
