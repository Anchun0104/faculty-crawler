from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import AppViewState
from ui.theme import COLORS, UTILITY_FONT


class StartPage(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        output_dir: tk.StringVar,
        status_text: tk.StringVar,
        on_validate: Callable[[str], AppViewState],
        on_change_output: Callable[[], None],
        on_start: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=(28, 24), style="TFrame")
        self._on_validate = on_validate
        self._status_text = status_text

        ttk.Label(self, text="开始采集", style="Heading.TLabel").pack(anchor=tk.W)
        ttk.Label(
            self,
            text="每行粘贴一个院系教师名录页网址，检查无误后开始。",
        ).pack(anchor=tk.W, pady=(4, 18))

        register = tk.Frame(
            self,
            background=COLORS["line_gray"],
            highlightbackground=COLORS["line_gray"],
            highlightthickness=1,
        )
        register.pack(fill=tk.BOTH, expand=True)
        self.line_gutter = tk.Text(
            register,
            width=7,
            padx=7,
            pady=8,
            state=tk.DISABLED,
            relief=tk.FLAT,
            background="#EAF0F5",
            foreground=COLORS["archive_blue"],
            font=UTILITY_FONT,
            takefocus=False,
        )
        self.line_gutter.pack(side=tk.LEFT, fill=tk.Y)
        self.url_text = tk.Text(
            register,
            height=12,
            padx=10,
            pady=8,
            wrap=tk.NONE,
            undo=True,
            relief=tk.FLAT,
            background="#FFFFFF",
            foreground=COLORS["archive_blue"],
            insertbackground=COLORS["archive_blue"],
            selectbackground=COLORS["data_teal"],
            font=UTILITY_FONT,
            highlightthickness=2,
            highlightbackground="#FFFFFF",
            highlightcolor=COLORS["data_teal"],
        )
        self.url_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar = ttk.Scrollbar(register, command=self._scroll_both)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_text.configure(yscrollcommand=self._on_url_scroll)
        self.url_text.bind("<KeyRelease>", self._validate)
        self.url_text.bind("<<Paste>>", lambda _event: self.after_idle(self._validate))
        self.url_text.bind("<MouseWheel>", lambda _event: self.after_idle(self._sync_gutter))

        self.count_text = tk.StringVar(value="已识别 0 个网址")
        ttk.Label(self, textvariable=self.count_text, style="Utility.TLabel").pack(
            anchor=tk.W, pady=(10, 2)
        )
        self.validation_text = tk.StringVar(value="○ 请粘贴教师名录页网址。")
        self.validation_label = ttk.Label(self, textvariable=self.validation_text)
        self.validation_label.pack(anchor=tk.W)

        output_row = ttk.Frame(self, padding=(0, 16, 0, 0))
        output_row.pack(fill=tk.X)
        ttk.Label(output_row, text="保存到").pack(side=tk.LEFT)
        ttk.Label(output_row, textvariable=output_dir, style="Utility.TLabel").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 10)
        )
        self.change_output_button = ttk.Button(
            output_row,
            text="更改位置",
            command=on_change_output,
            style="Secondary.TButton",
        )
        self.change_output_button.pack(side=tk.RIGHT)

        action_row = ttk.Frame(self, padding=(0, 18, 0, 0))
        action_row.pack(fill=tk.X)
        self.start_button = ttk.Button(
            action_row,
            text="检查并开始采集",
            command=on_start,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.start_button.pack(side=tk.RIGHT)
        self._render_gutter(())

    def raw_urls(self) -> str:
        return self.url_text.get("1.0", "end-1c")

    def set_state(self, state: AppViewState) -> None:
        self._replace_invalid_values(state.invalid_lines)
        self.count_text.set(f"已识别 {state.valid_count} 个网址")
        self.validation_text.set(f"{state.status_symbol} {state.status_text}")
        self._status_text.set(f"{state.status_symbol} {state.status_text}")
        style = "Warning.TLabel" if state.invalid_lines else "TLabel"
        self.validation_label.configure(style=style)
        self.start_button.configure(
            state=tk.NORMAL if state.can_start and not state.running else tk.DISABLED
        )
        self.change_output_button.configure(
            state=tk.DISABLED if state.running else tk.NORMAL
        )
        self.url_text.configure(state=tk.DISABLED if state.running else tk.NORMAL)
        self._render_gutter(state.invalid_lines)

    def _replace_invalid_values(
        self,
        invalid_lines: tuple[tuple[int, str], ...],
    ) -> None:
        raw = self.raw_urls()
        sanitized = _sanitized_input(raw, invalid_lines)
        if sanitized == raw:
            return
        current_state = str(self.url_text.cget("state"))
        self.url_text.configure(state=tk.NORMAL)
        self.url_text.delete("1.0", tk.END)
        self.url_text.insert("1.0", sanitized)
        self.url_text.configure(state=current_state)

    def _validate(self, _event=None) -> None:
        self.set_state(self._on_validate(self.raw_urls()))

    def _render_gutter(self, invalid_lines: tuple[tuple[int, str], ...]) -> None:
        invalid = {number for number, _value in invalid_lines}
        lines = self.raw_urls().splitlines() or [""]
        labels = [
            f"{'!' if number in invalid else '·'} {number}"
            for number in range(1, len(lines) + 1)
        ]
        self.line_gutter.configure(state=tk.NORMAL)
        self.line_gutter.delete("1.0", tk.END)
        self.line_gutter.insert("1.0", "\n".join(labels))
        self.line_gutter.configure(state=tk.DISABLED)
        self._sync_gutter()

    def _scroll_both(self, *args) -> None:
        self.url_text.yview(*args)
        self.line_gutter.yview_moveto(self.url_text.yview()[0])

    def _on_url_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        self.line_gutter.yview_moveto(float(first))

    def _sync_gutter(self) -> None:
        self.line_gutter.yview_moveto(self.url_text.yview()[0])


def _sanitized_input(
    raw_urls: str,
    invalid_lines: tuple[tuple[int, str], ...],
) -> str:
    if not invalid_lines:
        return raw_urls
    replacements = dict(invalid_lines)
    lines = raw_urls.splitlines(keepends=True)
    rendered: list[str] = []
    for number, line in enumerate(lines, start=1):
        replacement = replacements.get(number)
        if replacement is None:
            rendered.append(line)
            continue
        if line.endswith("\r\n"):
            ending = "\r\n"
        elif line.endswith("\n"):
            ending = "\n"
        else:
            ending = ""
        rendered.append(replacement + ending)
    return "".join(rendered)
