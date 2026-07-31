from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
from typing import Any, Callable

from crawler.app_paths import AppPaths
from faculty_workflow.ai_settings import AiSettingsStore, ProviderConfiguration
from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import DisciplinePolicy
from faculty_workflow.providers import DeepSeekProvider
from faculty_workflow.service import WorkflowService

REVIEW_VISIBLE_STATUSES = ("review", "candidate", "unresolved")


class WorkflowDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("通用专业教授自动采集系统")
        self.geometry("1180x800")
        self.minsize(980, 680)
        self.app_paths = AppPaths.for_user()
        self.workflow_root = self.app_paths.root / "workflow"
        self.database = WorkflowDatabase(self.workflow_root / "workflow.db")
        self.ai_settings = AiSettingsStore(self.app_paths.settings / "workflow-ai")
        self.ai_configuration, self.ai_key = self.ai_settings.load()
        self.service = self._make_service()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.current_task = tk.StringVar()
        self.status_text = tk.StringVar(value="请新建或载入任务。")
        self._build()
        self.after(200, self._drain_events)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=8)
        header.pack(fill=tk.X)
        ttk.Label(header, text="任务 ID：").pack(side=tk.LEFT)
        ttk.Entry(header, textvariable=self.current_task, width=18).pack(side=tk.LEFT)
        ttk.Button(header, text="载入", command=self._refresh_all).pack(side=tk.LEFT, padx=5)
        api_state = "已检测到 DEEPSEEK_API_KEY" if os.environ.get("DEEPSEEK_API_KEY") else "未配置 DEEPSEEK_API_KEY"
        ttk.Label(header, text=api_state).pack(side=tk.RIGHT)

        ttk.Button(header, text="AI settings", command=self._open_ai_settings).pack(side=tk.RIGHT)
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.direct_tab = ttk.Frame(notebook, padding=10)
        self.new_tab = ttk.Frame(notebook, padding=10)
        self.progress_tab = ttk.Frame(notebook, padding=10)
        self.review_tab = ttk.Frame(notebook, padding=10)
        self.export_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.new_tab, text="1. 新建任务")
        notebook.add(self.progress_tab, text="2. 运行进度")
        notebook.add(self.review_tab, text="3. 人工复核")
        notebook.add(self.export_tab, text="4. 导出审计")
        notebook.add(self.direct_tab, text="Direct URL")
        self._build_direct_tab()
        self._build_new_tab()
        self._build_progress_tab()
        self._build_review_tab()
        self._build_export_tab()
        ttk.Label(self, textvariable=self.status_text, anchor=tk.W).pack(fill=tk.X, padx=10, pady=(0, 8))

    def _make_service(self) -> WorkflowService:
        provider = self.ai_settings.build_provider(self.ai_configuration, self.ai_key)
        return WorkflowService(self.database, provider=provider or DeepSeekProvider(api_key=""))

    def _open_ai_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("AI settings")
        provider = tk.StringVar(value=self.ai_configuration.provider if self.ai_configuration.enabled else "deepseek")
        base_url = tk.StringVar(value=self.ai_configuration.base_url)
        model = tk.StringVar(value=self.ai_configuration.model or "deepseek-v4-flash")
        api_key = tk.StringVar(value="")
        for row, (label, variable, show) in enumerate((("Provider", provider, ""), ("Base URL", base_url, ""), ("Model", model, ""), ("API key", api_key, "*"))):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky=tk.W, padx=8, pady=5)
            ttk.Entry(dialog, textvariable=variable, show=show).grid(row=row, column=1, sticky=tk.EW, padx=8, pady=5)
        def save() -> None:
            selected = provider.get().strip()
            config = ProviderConfiguration.deepseek(model=model.get().strip()) if selected == "deepseek" and not base_url.get().strip() else ProviderConfiguration(True, selected, base_url.get().strip(), model.get().strip())
            self.ai_settings.save(config, api_key.get() or self.ai_key)
            self.ai_configuration, self.ai_key = self.ai_settings.load()
            self.service = self._make_service()
            dialog.destroy()
        def local() -> None:
            self.ai_settings.save(ProviderConfiguration.local(), "")
            self.ai_configuration, self.ai_key = self.ai_settings.load()
            self.service = self._make_service()
            dialog.destroy()
        def test_connection() -> None:
            selected = provider.get().strip()
            config = ProviderConfiguration.deepseek(model=model.get().strip()) if selected == "deepseek" and not base_url.get().strip() else ProviderConfiguration(True, selected, base_url.get().strip(), model.get().strip())
            self._background("ai_test", lambda: self.ai_settings.test_connection(config, api_key.get() or self.ai_key))
        def delete_key() -> None:
            self.ai_settings.delete_key()
            self.ai_key = ""
            api_key.set("")
        ttk.Button(dialog, text="Save", command=save).grid(row=4, column=0, padx=8, pady=8, sticky=tk.EW)
        ttk.Button(dialog, text="Local mode", command=local).grid(row=4, column=1, padx=8, pady=8, sticky=tk.EW)
        ttk.Button(dialog, text="Test connection", command=test_connection).grid(row=5, column=0, padx=8, pady=(0, 8), sticky=tk.EW)
        ttk.Button(dialog, text="Delete saved key", command=delete_key).grid(row=5, column=1, padx=8, pady=(0, 8), sticky=tk.EW)
        dialog.columnconfigure(1, weight=1)

    def _build_direct_tab(self) -> None:
        self.direct_urls = tk.StringVar()
        self.direct_school = tk.StringVar()
        self.direct_discipline = tk.StringVar(value="General Faculty")
        self.direct_output_dir = tk.StringVar(value=str(Path.cwd() / "workflow_output"))
        self.direct_budget = tk.StringVar(value="20")
        self.direct_use_ai = tk.BooleanVar(value=False)
        fields = (("Verified directory URLs (; separated)", self.direct_urls), ("School override (one URL only)", self.direct_school), ("Discipline", self.direct_discipline), ("Output directory", self.direct_output_dir), ("Budget USD", self.direct_budget))
        for row, (label, variable) in enumerate(fields):
            ttk.Label(self.direct_tab, text=label).grid(row=row, column=0, sticky=tk.W, pady=5)
            ttk.Entry(self.direct_tab, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, padx=6)
        ttk.Button(self.direct_tab, text="Choose", command=lambda: self._pick_dir(self.direct_output_dir)).grid(row=3, column=2)
        ttk.Checkbutton(self.direct_tab, text="Use configured AI for supplied-page parsing only", variable=self.direct_use_ai).grid(row=5, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(self.direct_tab, text="AI never searches for, guesses, or replaces a directory URL; it never guesses an email.", wraplength=700).grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=8)
        ttk.Button(self.direct_tab, text="Create and run evidence task", command=self._run_direct_task).grid(row=7, column=0, columnspan=3, sticky=tk.EW)
        self.direct_tab.columnconfigure(1, weight=1)

    def _run_direct_task(self) -> None:
        try:
            budget = float(self.direct_budget.get())
        except ValueError:
            messagebox.showerror("Budget", "Budget must be a number")
            return
        if self.direct_use_ai.get() and not self.ai_configuration.enabled:
            messagebox.showerror("AI", "AI is disabled. Configure a provider before enabling it.")
            return
        urls = [item.strip() for item in self.direct_urls.get().replace("\n", ";").split(";") if item.strip()]
        def create_and_run() -> tuple[str, dict[str, Any]]:
            task_id = self.service.create_direct_url_task(directory_urls=urls, output_dir=self.direct_output_dir.get(), school_name=self.direct_school.get(), discipline=self.direct_discipline.get(), use_ai=self.direct_use_ai.get(), routine_model=self.ai_configuration.model or "deepseek-v4-flash", escalation_model=self.ai_configuration.model or "deepseek-v4-pro", budget_usd=budget)
            return task_id, self.service.run_task(task_id)
        self._background("direct_run", create_and_run)

    def _build_new_tab(self) -> None:
        self.school_path = tk.StringVar()
        self.discipline = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "workflow_output"))
        self.history_paths = tk.StringVar()
        self.processed_paths = tk.StringVar()
        self.budget = tk.StringVar(value="20")
        self.no_model = tk.BooleanVar(value=True)
        fields = [
            ("学校名单 CSV/XLSX（需填写教师目录）", self.school_path, lambda: self._pick_file(self.school_path)),
            ("目标专业", self.discipline, None),
            ("输出目录", self.output_dir, lambda: self._pick_dir(self.output_dir)),
            ("历史教授文件（分号分隔）", self.history_paths, lambda: self._pick_files(self.history_paths)),
            ("已完成学校文件（分号分隔）", self.processed_paths, lambda: self._pick_files(self.processed_paths)),
            ("API 预算（美元）", self.budget, None),
        ]
        for row, (label, variable, action) in enumerate(fields):
            ttk.Label(self.new_tab, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            ttk.Entry(self.new_tab, textvariable=variable).grid(row=row, column=1, sticky=tk.EW, padx=6)
            if action:
                ttk.Button(self.new_tab, text="选择", command=action).grid(row=row, column=2)
        ttk.Checkbutton(self.new_tab, text="不使用模型（仅官方目录与本地规则）", variable=self.no_model).grid(
            row=len(fields), column=0, columnspan=3, sticky=tk.W, pady=(4, 0)
        )
        self.new_tab.columnconfigure(1, weight=1)
        ttk.Label(
            self.new_tab,
            text="Required: every school row must provide a verified directory_url.\nAI never searches for or guesses directory URLs.",
            justify=tk.LEFT,
            wraplength=300,
        ).grid(row=0, column=3, rowspan=2, sticky=tk.NW, padx=(8, 0))
        ttk.Button(self.new_tab, text="生成任务与专业口径草案", command=self._create_task).grid(
            row=len(fields) + 1, column=0, columnspan=3, sticky=tk.EW, pady=8
        )
        ttk.Label(self.new_tab, text="专业口径 JSON（确认前可编辑）").grid(
            row=len(fields) + 2, column=0, columnspan=3, sticky=tk.W
        )
        self.policy_text = scrolledtext.ScrolledText(self.new_tab, height=18, wrap=tk.WORD)
        self.policy_text.grid(row=len(fields) + 3, column=0, columnspan=3, sticky=tk.NSEW)
        self.new_tab.rowconfigure(len(fields) + 3, weight=1)
        ttk.Button(self.new_tab, text="确认专业口径", command=self._confirm_policy).grid(
            row=len(fields) + 4, column=0, columnspan=3, sticky=tk.EW, pady=(8, 0)
        )

    def _build_progress_tab(self) -> None:
        toolbar = ttk.Frame(self.progress_tab)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="开始/继续运行", command=self._run_task).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="刷新", command=self._refresh_progress).pack(side=tk.LEFT, padx=6)
        ttk.Label(toolbar, text="预算上限 $").pack(side=tk.LEFT, padx=(20, 2))
        self.new_budget = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.new_budget, width=9).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="更新预算并恢复", command=self._set_budget).pack(side=tk.LEFT, padx=5)
        self.progress_label = ttk.Label(toolbar, text="")
        self.progress_label.pack(side=tk.RIGHT)
        columns = ("row", "school", "status", "domain", "reason")
        self.school_tree = ttk.Treeview(self.progress_tab, columns=columns, show="headings")
        for column, heading, width in (
            ("row", "编号", 70), ("school", "学校", 300), ("status", "状态", 120),
            ("domain", "官方域名", 220), ("reason", "失败/复核原因", 360),
        ):
            self.school_tree.heading(column, text=heading)
            self.school_tree.column(column, width=width)
        self.school_tree.pack(fill=tk.BOTH, expand=True, pady=8)

    def _build_review_tab(self) -> None:
        toolbar = ttk.Frame(self.review_tab)
        toolbar.pack(fill=tk.X)
        ttk.Button(
            toolbar,
            text="仅重新处理复核队列",
            command=self._run_review_generation,
        ).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="刷新待复核记录", command=self._refresh_review).pack(side=tk.LEFT)
        ttk.Label(self.review_tab, text="Access review queue").pack(anchor=tk.W, pady=(8, 0))
        access_columns = ("id", "school", "url", "reason", "status")
        self.access_tree = ttk.Treeview(self.review_tab, columns=access_columns, show="headings", height=5)
        for column, heading, width in (
            ("id", "ID", 55), ("school", "School", 230), ("url", "URL", 360),
            ("reason", "Reason", 270), ("status", "Status", 130),
        ):
            self.access_tree.heading(column, text=heading)
            self.access_tree.column(column, width=width)
        self.access_tree.pack(fill=tk.X, pady=5)
        access_actions = ttk.Frame(self.review_tab)
        access_actions.pack(fill=tk.X)
        ttk.Button(access_actions, text="Open verification browser", command=self._begin_access_verification).pack(side=tk.LEFT)
        ttk.Button(access_actions, text="Save verified session and retry", command=self._finish_access_verification).pack(side=tk.LEFT, padx=6)
        ttk.Button(access_actions, text="Close verification browser", command=self._cancel_access_verification).pack(side=tk.LEFT)
        ttk.Button(access_actions, text="Requeue school for retry", command=self._retry_access_review).pack(side=tk.LEFT)
        ttk.Button(access_actions, text="Dismiss", command=self._dismiss_access_review).pack(side=tk.LEFT, padx=6)
        ttk.Label(self.review_tab, text="Candidate data review").pack(anchor=tk.W, pady=(10, 0))
        columns = ("id", "name", "school", "email", "title", "reason")
        self.review_tree = ttk.Treeview(self.review_tab, columns=columns, show="headings", height=10)
        for column, heading, width in (
            ("id", "ID", 55), ("name", "姓名", 160), ("school", "学校", 230),
            ("email", "邮箱", 200), ("title", "职称", 130), ("reason", "原因", 330),
        ):
            self.review_tree.heading(column, text=heading)
            self.review_tree.column(column, width=width)
        self.review_tree.pack(fill=tk.X, pady=8)
        self.review_tree.bind("<<TreeviewSelect>>", self._show_review)
        editor = ttk.Frame(self.review_tab)
        editor.pack(fill=tk.X)
        keys = ("name", "email", "last_name", "normalized_title", "department", "homepage")
        self.review_vars = {key: tk.StringVar() for key in keys}
        labels = {"name": "姓名", "email": "邮箱", "last_name": "last name", "normalized_title": "规范职称", "department": "院系", "homepage": "个人主页"}
        for index, key in enumerate(keys):
            ttk.Label(editor, text=labels[key]).grid(row=index // 2, column=(index % 2) * 2, sticky=tk.W, pady=3)
            ttk.Entry(editor, textvariable=self.review_vars[key]).grid(row=index // 2, column=(index % 2) * 2 + 1, sticky=tk.EW, padx=5)
        editor.columnconfigure(1, weight=1)
        editor.columnconfigure(3, weight=1)
        self.evidence_text = scrolledtext.ScrolledText(self.review_tab, height=10, wrap=tk.WORD)
        self.evidence_text.pack(fill=tk.BOTH, expand=True, pady=8)
        decisions = ttk.Frame(self.review_tab)
        decisions.pack(fill=tk.X)
        ttk.Button(
            decisions,
            text="Reopen unresolved",
            command=self._reopen_unresolved,
        ).pack(side=tk.RIGHT)
        ttk.Button(decisions, text="保存并接受", command=lambda: self._decide("accepted")).pack(side=tk.LEFT)
        ttk.Button(decisions, text="拒绝", command=lambda: self._decide("rejected")).pack(side=tk.LEFT, padx=6)
        ttk.Button(decisions, text="继续保留复核", command=lambda: self._decide("review")).pack(side=tk.LEFT)
        ttk.Button(decisions, text="重新处理本校", command=self._reprocess).pack(side=tk.LEFT, padx=6)

    def _build_export_tab(self) -> None:
        ttk.Button(self.export_tab, text="生成正式表、复核表和审计 JSON", command=self._export).pack(fill=tk.X)
        self.audit_text = scrolledtext.ScrolledText(self.export_tab, wrap=tk.WORD)
        self.audit_text.pack(fill=tk.BOTH, expand=True, pady=8)

    def _create_task(self) -> None:
        try:
            budget = float(self.budget.get())
        except ValueError:
            messagebox.showerror("预算", "预算必须是数字")
            return
        self._background("create", lambda: self.service.create_task(
            schools_path=self.school_path.get(), discipline=self.discipline.get(),
            output_dir=self.output_dir.get(), budget_usd=budget,
            history_paths=_split_paths(self.history_paths.get()),
            processed_school_paths=_split_paths(self.processed_paths.get()),
            generate_ai_policy=not self.no_model.get(),
            routine_model="local-only" if self.no_model.get() else "deepseek-v4-flash",
            escalation_model="local-only" if self.no_model.get() else "deepseek-v4-pro",
        ))

    def _confirm_policy(self) -> None:
        task_id = self._task_id()
        if not task_id:
            return
        try:
            self.service.confirm_policy(task_id, DisciplinePolicy.from_json(self.policy_text.get("1.0", tk.END)))
        except Exception as exc:
            messagebox.showerror("专业口径", str(exc))
            return
        self.status_text.set("专业口径已确认，可以运行任务。")
        self._refresh_all()

    def _run_task(self) -> None:
        task_id = self._task_id()
        if task_id:
            self._background("run", lambda: self.service.run_task(
                task_id, on_progress=lambda event: self.events.put(("progress", event))
            ))

    def _run_review_generation(self) -> None:
        task_id = self._task_id()
        if task_id:
            self._background("review_generation", lambda: self.service.run_review_generation(
                task_id, on_progress=lambda event: self.events.put(("progress", event))
            ))

    def _set_budget(self) -> None:
        task_id = self._task_id()
        if not task_id:
            return
        try:
            self.database.set_budget(task_id, float(self.new_budget.get()))
        except Exception as exc:
            messagebox.showerror("预算", str(exc))
            return
        self.status_text.set("预算已更新；任务可继续运行。")
        self._refresh_progress()

    def _export(self) -> None:
        task_id = self._task_id()
        if task_id:
            self._background("export", lambda: self.service.export(task_id))

    def _refresh_all(self) -> None:
        task_id = self._task_id()
        if not task_id:
            return
        try:
            policy = self.database.get_policy(task_id)
        except Exception as exc:
            messagebox.showerror("任务", str(exc))
            return
        self.policy_text.delete("1.0", tk.END)
        self.policy_text.insert("1.0", json.dumps(json.loads(policy.to_json()), ensure_ascii=False, indent=2))
        self._refresh_progress()
        self._refresh_review()
        self.audit_text.delete("1.0", tk.END)
        self.audit_text.insert("1.0", json.dumps(self.database.summary(task_id), ensure_ascii=False, indent=2, default=str))

    def _refresh_progress(self) -> None:
        task_id = self._task_id(silent=True)
        if not task_id:
            return
        for item in self.school_tree.get_children():
            self.school_tree.delete(item)
        for school in self.database.list_schools(task_id):
            self.school_tree.insert("", tk.END, values=(school["original_row"], school["name"], school["status"], school["official_domain"], school["failure_reason"]))
        summary = self.database.summary(task_id)
        self.new_budget.set(str(summary["budget_usd"]))
        self.progress_label.configure(text=f"状态 {summary['status']} | 费用 ${summary['spent_usd']:.4f}/${summary['budget_usd']:.2f}")

    def _refresh_review(self) -> None:
        task_id = self._task_id(silent=True)
        if not task_id:
            return
        for item in self.review_tree.get_children():
            self.review_tree.delete(item)
        for item in self.access_tree.get_children():
            self.access_tree.delete(item)
        for row in self.database.list_access_reviews(task_id, ["pending"]):
            self.access_tree.insert(
                "", tk.END, iid=str(row["id"]),
                values=(row["id"], row["school"], row["url"], row["reason"], row["status"]),
            )
        for row in self.database.list_candidates(task_id, REVIEW_VISIBLE_STATUSES):
            self.review_tree.insert(
                "", tk.END,
                iid=str(row["id"]),
                values=(
                    row["id"], row["name"], row["school"], row["email"],
                    row["normalized_title"], f"{row['status']}: {row['review_reason']}",
                ),
            )

    def _show_review(self, _event: object | None = None) -> None:
        selected = self.review_tree.selection()
        if not selected:
            return
        candidate_id = int(selected[0])
        row = next(row for row in self.database.list_candidates(self.current_task.get()) if row["id"] == candidate_id)
        for key, variable in self.review_vars.items():
            variable.set(row[key])
        self.evidence_text.delete("1.0", tk.END)
        self.evidence_text.insert("1.0", json.dumps(json.loads(row["evidence_json"]), ensure_ascii=False, indent=2))

    def _decide(self, decision: str) -> None:
        selected = self.review_tree.selection()
        if not selected:
            messagebox.showinfo("复核", "请先选择一条记录")
            return
        self.database.decide_candidate(
            int(selected[0]), decision, note="desktop_review",
            edits={key: value.get() for key, value in self.review_vars.items()},
        )
        self._refresh_review()

    def _reprocess(self) -> None:
        selected = self.review_tree.selection()
        if not selected:
            messagebox.showinfo("复核", "请先选择一条记录")
            return
        self.database.reprocess_candidate(int(selected[0]))
        self.status_text.set("该记录已标记为旧版本，学校已回到 pending；请继续运行任务。")
        self._refresh_all()

    def _reopen_unresolved(self) -> None:
        selected = self.review_tree.selection()
        if not selected:
            messagebox.showinfo("Reopen unresolved", "Select an unresolved record first.")
            return
        candidate_id = int(selected[0])
        row = next(
            row for row in self.database.list_candidates(self.current_task.get())
            if row["id"] == candidate_id
        )
        if row["status"] != "unresolved":
            messagebox.showinfo("Reopen unresolved", "Only unresolved records can be reopened.")
            return
        reason = simpledialog.askstring(
            "Reopen unresolved",
            "Describe the changed rule, official URL, or access condition:",
            parent=self,
        )
        if not reason or not reason.strip():
            return
        task_id = self._task_id()
        if task_id:
            self._background(
                "reopen_unresolved",
                lambda: self.service.reopen_unresolved(
                    task_id,
                    candidate_ids=[candidate_id],
                    reason=reason.strip(),
                ),
            )

    def _retry_access_review(self) -> None:
        selected = self.access_tree.selection()
        if not selected:
            messagebox.showinfo("Access review", "Select a blocked school first.")
            return
        self.database.resolve_access_review(int(selected[0]), retry=True)
        self.status_text.set("School requeued. Start or continue the task when ready.")
        self._refresh_all()

    def _begin_access_verification(self) -> None:
        selected = self.access_tree.selection()
        if not selected:
            messagebox.showinfo("Access review", "Select a blocked school first.")
            return
        try:
            self.service.begin_access_verification(int(selected[0]))
        except Exception as exc:
            messagebox.showerror("Access review", str(exc))
            return
        self.status_text.set("Complete the site's permitted verification in the visible browser, then save the session.")

    def _finish_access_verification(self) -> None:
        selected = self.access_tree.selection()
        if not selected:
            messagebox.showinfo("Access review", "Select the school whose browser you verified.")
            return
        try:
            self.service.finish_access_verification(int(selected[0]))
        except Exception as exc:
            messagebox.showerror("Access review", str(exc))
            return
        self.status_text.set("Encrypted site session saved; school requeued.")
        self._refresh_all()

    def _cancel_access_verification(self) -> None:
        self.service.cancel_access_verification()
        self.status_text.set("Verification browser closed; no session was saved.")

    def _dismiss_access_review(self) -> None:
        selected = self.access_tree.selection()
        if not selected:
            messagebox.showinfo("Access review", "Select a blocked school first.")
            return
        self.database.resolve_access_review(int(selected[0]), retry=False)
        self._refresh_review()

    def _background(self, operation: str, function: Callable[[], Any]) -> None:
        self.status_text.set(f"正在执行：{operation}")

        def worker() -> None:
            try:
                self.events.put((operation, function()))
            except Exception as exc:
                self.events.put(("error", (operation, str(exc))))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "create":
                self.current_task.set(str(payload))
                self.status_text.set(f"任务已创建：{payload}，请检查并确认专业口径。")
                self._refresh_all()
            elif kind == "progress":
                self._refresh_progress()
            elif kind == "run":
                self.status_text.set("任务运行结束。")
                self._refresh_all()
            elif kind == "direct_run":
                task_id, _summary = payload
                self.current_task.set(task_id)
                self.status_text.set("Direct URL task finished. Review and export are available in the remaining tabs.")
                self._refresh_all()
            elif kind == "ai_test":
                self.status_text.set(f"AI connection succeeded: {payload.model}")
            elif kind == "review_generation":
                self.status_text.set("复核队列重新处理完成；已完成记录保持不变。")
                self._refresh_all()
            elif kind == "reopen_unresolved":
                self.status_text.set(f"Reopened {payload['reopened']} unresolved record(s).")
                self._refresh_all()
            elif kind == "export":
                self.status_text.set("导出完成。")
                self.audit_text.delete("1.0", tk.END)
                self.audit_text.insert("1.0", json.dumps({key: str(value) for key, value in payload.items()}, ensure_ascii=False, indent=2))
            elif kind == "error":
                operation, message = payload
                self.status_text.set(f"{operation} 失败")
                messagebox.showerror("操作失败", message)
        self.after(200, self._drain_events)

    def _task_id(self, silent: bool = False) -> str:
        value = self.current_task.get().strip()
        if not value and not silent:
            messagebox.showinfo("任务", "请先输入或创建任务 ID")
        return value

    def _pick_file(self, variable: tk.StringVar) -> None:
        value = filedialog.askopenfilename(filetypes=[("School files", "*.csv *.xlsx")])
        if value:
            variable.set(value)

    def _pick_files(self, variable: tk.StringVar) -> None:
        values = filedialog.askopenfilenames(filetypes=[("Data files", "*.xlsx *.csv *.json *.txt")])
        if values:
            variable.set(";".join(values))

    def _pick_dir(self, variable: tk.StringVar) -> None:
        value = filedialog.askdirectory(initialdir=variable.get() or None)
        if value:
            variable.set(value)


def _split_paths(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def main() -> None:
    WorkflowDesktopApp().mainloop()


if __name__ == "__main__":
    main()
