from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ui.controller import SettingsView, StorageSummary


class SettingsPage(ttk.Frame):
    def __init__(
        self,
        master,
        *,
        on_save: Callable[..., SettingsView],
        on_change_output: Callable[[], None],
        on_clear_temporary: Callable[[], None],
        on_clear_internal: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=(28, 24))
        self._on_save = on_save
        self.output_dir = tk.StringVar()
        self.feishu_url = tk.StringVar()
        self.detailed_logs = tk.BooleanVar()
        self.timeout_ms = tk.StringVar(value="30000")
        self.translation_endpoint = tk.StringVar()
        self.translation_cache_path = tk.StringVar()
        self.translation_connect_timeout = tk.StringVar()
        self.translation_response_timeout = tk.StringVar()
        self.translation_retries = tk.StringVar()
        self.message = tk.StringVar()
        ttk.Label(self, text="设置", style="Heading.TLabel").grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 18))
        ttk.Label(self, text="结果保存位置").grid(row=1, column=0, sticky=tk.W, pady=7)
        ttk.Entry(self, textvariable=self.output_dir).grid(row=1, column=1, sticky=tk.EW, padx=12, pady=7)
        ttk.Button(self, text="更改位置", command=on_change_output, style="Secondary.TButton").grid(row=1, column=2)
        ttk.Label(self, text="飞书共享文件夹网址").grid(row=2, column=0, sticky=tk.W, pady=7)
        ttk.Entry(self, textvariable=self.feishu_url).grid(row=2, column=1, columnspan=2, sticky=tk.EW, padx=(12, 0), pady=7)

        self.advanced_button = ttk.Button(self, text="高级设置", command=self._toggle_advanced, style="Secondary.TButton")
        self.advanced_button.grid(row=3, column=0, sticky=tk.W, pady=(16, 8))
        self.advanced = ttk.Frame(self)
        ttk.Label(self.advanced, text="网页等待时间（毫秒）").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(self.advanced, textvariable=self.timeout_ms, width=14).grid(row=0, column=1, sticky=tk.W, padx=10)
        ttk.Checkbutton(self.advanced, text="保存详细日志", variable=self.detailed_logs).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Label(self.advanced, text="本机翻译地址").grid(row=2, column=0, sticky=tk.W, pady=(12, 0))
        ttk.Entry(self.advanced, textvariable=self.translation_endpoint, width=32).grid(row=2, column=1, sticky=tk.W, padx=10, pady=(12, 0))
        ttk.Label(self.advanced, text="翻译缓存路径").grid(row=3, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(self.advanced, textvariable=self.translation_cache_path, width=32).grid(row=3, column=1, sticky=tk.W, padx=10, pady=(6, 0))
        ttk.Label(self.advanced, text="翻译连接/响应超时（秒）").grid(row=4, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(self.advanced, textvariable=self.translation_connect_timeout, width=8).grid(row=4, column=1, sticky=tk.W, padx=10, pady=(6, 0))
        ttk.Entry(self.advanced, textvariable=self.translation_response_timeout, width=8).grid(row=4, column=1, sticky=tk.E, pady=(6, 0))
        ttk.Label(self.advanced, text="翻译重试次数").grid(row=5, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Entry(self.advanced, textvariable=self.translation_retries, width=8).grid(row=5, column=1, sticky=tk.W, padx=10, pady=(6, 0))
        self._advanced_visible = False

        ttk.Button(self, text="保存设置", command=self._save, style="Primary.TButton").grid(row=4, column=2, sticky=tk.E, pady=(18, 12))
        self.message_label = ttk.Label(self, textvariable=self.message)
        self.message_label.grid(row=5, column=0, columnspan=3, sticky=tk.W)
        ttk.Separator(self).grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=20)
        ttk.Label(self, text="内部存储", style="Section.TLabel").grid(row=7, column=0, sticky=tk.W)
        self.storage_text = tk.StringVar(value="0 个文件 · 0 B")
        ttk.Label(self, textvariable=self.storage_text, style="Utility.TLabel").grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=(8, 2))
        self.storage_categories = tk.StringVar()
        ttk.Label(self, textvariable=self.storage_categories).grid(row=9, column=0, columnspan=3, sticky=tk.W)
        cleanup = ttk.Frame(self)
        cleanup.grid(row=10, column=0, columnspan=3, sticky=tk.EW, pady=(14, 0))
        ttk.Button(cleanup, text="清理临时文件", command=on_clear_temporary, style="Secondary.TButton").pack(side=tk.LEFT)
        ttk.Button(cleanup, text="清除内部数据", command=on_clear_internal, style="Destructive.TButton").pack(side=tk.LEFT, padx=(8, 0))
        self.columnconfigure(1, weight=1)

    def set_state(self, settings: SettingsView, storage: StorageSummary) -> None:
        self.output_dir.set(settings.output_dir)
        self.feishu_url.set(settings.feishu_folder_url)
        self.detailed_logs.set(settings.detailed_logs)
        self.timeout_ms.set(str(settings.timeout_ms))
        self.translation_endpoint.set(settings.translation.endpoint)
        self.translation_cache_path.set(settings.translation.cache_path)
        self.translation_connect_timeout.set(str(settings.translation.connect_timeout))
        self.translation_response_timeout.set(str(settings.translation.response_timeout))
        self.translation_retries.set(str(settings.translation.retries))
        self.message.set(settings.error)
        self.message_label.configure(style="Failure.TLabel" if settings.error else "TLabel")
        self.storage_text.set(f"{storage.files} 个文件 · {_format_bytes(storage.total_bytes)}")
        self.storage_categories.set("、".join(storage.categories))

    def set_output_dir(self, output_dir: str) -> None:
        self.output_dir.set(output_dir)

    def focus_primary(self) -> None:
        self.focus_set()

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=(16, 8))
            self.advanced_button.configure(text="收起高级设置")
        else:
            self.advanced.grid_forget()
            self.advanced_button.configure(text="高级设置")

    def _save(self) -> None:
        try:
            timeout = int(self.timeout_ms.get())
        except ValueError:
            timeout = 0
        try:
            translation_connect_timeout = float(self.translation_connect_timeout.get())
            translation_response_timeout = float(self.translation_response_timeout.get())
            translation_retries = int(self.translation_retries.get())
        except ValueError:
            self.message.set("翻译设置必须为有效本机地址、非空缓存路径、正超时和非负重试次数")
            self.message_label.configure(style="Failure.TLabel")
            return
        state = self._on_save(
            self.output_dir.get(),
            self.feishu_url.get(),
            self.detailed_logs.get(),
            timeout,
            translation_endpoint=self.translation_endpoint.get(),
            translation_cache_path=self.translation_cache_path.get(),
            translation_connect_timeout=translation_connect_timeout,
            translation_response_timeout=translation_response_timeout,
            translation_retries=translation_retries,
        )
        self.message.set(state.error or "设置已保存")
        self.message_label.configure(style="Failure.TLabel" if state.error else "TLabel")


def _format_bytes(value: int) -> str:
    if value < 1024: return f"{value} B"
    if value < 1024 * 1024: return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"
