# GitHub 源码包 2.1.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 生成不含运行数据、可直接上传 GitHub 的 faculty-crawler `2.1.0` 完整源码包及中文发布材料。

**架构：** 保留现有确定性 ZIP 构建器，用显式根文件清单和受控目录递归扩展发布边界。测试直接构建真实 ZIP 并断言关键文件存在、敏感路径与扩展名不存在；最终交付物放在 Git worktree 外。

**技术栈：** Python 3、`zipfile`、`unittest`、PowerShell SHA-256。

## 全局约束

- 唯一版本号为 `2.1.0`，来源为根目录 `VERSION`。
- 包含 `crawler`、`faculty_workflow`、`ui`、`scripts`、`tests`、工作流入口、构建文件和用户文档。
- 排除 `.git`、`.venv`、`.codex`、`workflow_data`、数据库、快照、生成表格、日志、缓存、构建输出和 Python 字节码。
- 不提交、不推送、不合并、不删除当前 worktree。

---

### 任务 1：锁定完整源码包契约

**文件：**
- 修改：`tests/test_release.py`
- 修改：`build_release.py`

**接口：**
- 消费：`build_archive(project_root: Path, dist_dir: Path) -> Path`
- 产出：包含新增工作流、脚本和测试的确定性 ZIP。

- [ ] **步骤 1：先写失败测试**

在 `tests/test_release.py` 增加真实 ZIP 行为测试，手工声明必须存在的文件：

```python
required = {
    "faculty-crawler-windows/workflow.py",
    "faculty-crawler-windows/workflow_desktop.py",
    "faculty-crawler-windows/faculty_workflow/service.py",
    "faculty-crawler-windows/scripts/validate_task_acceptance.py",
    "faculty-crawler-windows/tests/test_workflow_service.py",
    "faculty-crawler-windows/RELEASE_NOTES_2.1.0.md",
}
```

同时断言 ZIP 成员不以 `.git/`、`.venv/`、`.codex/`、`workflow_data/` 开头，且不以 `.db`、`.sqlite3`、`.xlsx`、`.log`、`.pyc` 结尾。

- [ ] **步骤 2：验证测试按预期失败**

运行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release.ReleasePackageTests.test_release_contains_evidence_workflow_and_excludes_runtime_data
```

预期：因 `workflow.py` 或 `faculty_workflow/service.py` 不在 ZIP 中而失败。

- [ ] **步骤 3：实现最小发布清单扩展**

在 `build_release.py` 中：

```python
_SOURCE_PACKAGES = ("crawler", "faculty_workflow", "scripts", "tests", "ui")
_SOURCE_SUFFIXES = {".py"}
```

把 `workflow.py`、`workflow_desktop.py`、`RELEASE_NOTES_2.1.0.md` 加入根文件清单，并对上述目录只递归纳入 `.py` 文件。继续使用显式 `RELEASE_FILES` 写入 ZIP，不扫描运行数据目录。

- [ ] **步骤 4：验证发布契约通过**

运行任务 1 的单项测试以及完整 `tests.test_release`，预期全部通过。

### 任务 2：升级版本与中文发布说明

**文件：**
- 修改：`VERSION`
- 修改：`README.md`
- 修改：`tests/test_release.py`
- 创建：`RELEASE_NOTES_2.1.0.md`

**接口：**
- 产出：构建器和安装器读取到统一版本 `2.1.0`。

- [ ] **步骤 1：先把版本测试期望改为 `2.1.0` 并验证失败**

运行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release.ReleasePackageTests.test_release_uses_single_version_source
```

预期：当前 `VERSION` 为 `2.0.0`，测试失败。

- [ ] **步骤 2：写入版本与中文发布说明**

将 `VERSION` 改为 `2.1.0`；README 当前版本描述同步为 `2.1.0`，保留 `2.0.0` 的历史功能说明和已发布安装包链接。发布说明列出 local-only、证据工作流、官方 PDF/缓存、二级来源发现、复核重处理、边界过滤以及验证命令。

- [ ] **步骤 3：验证版本测试和发布测试通过**

运行完整 `tests.test_release`，预期全部通过。

### 任务 3：生成并审计 GitHub 上传包

**文件：**
- 生成：工作区外 `faculty-crawler-2.1.0-github-upload/`

**接口：**
- 产出：ZIP、`SHA256SUMS.txt`、`文件清单.txt`、`上传说明.md`。

- [ ] **步骤 1：运行完整验证**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall crawler faculty_workflow scripts workflow.py workflow_desktop.py
git diff --check
```

- [ ] **步骤 2：调用真实构建器生成 ZIP**

运行 `python build_release.py`，把生成的确定性 ZIP 复制到 worktree 外并命名为 `faculty-crawler-2.1.0-source.zip`。

- [ ] **步骤 3：生成清单和 SHA-256**

读取 ZIP 成员生成 UTF-8 中文文件清单；用 `Get-FileHash -Algorithm SHA256` 生成校验文件；写中文上传说明，包含版本、分支、测试数量、主要变更和建议 GitHub Release 文案。

- [ ] **步骤 4：最终复核**

再次打开交付 ZIP，验证必需成员、排除路径、文件数量和 SHA-256，并报告绝对路径；保持 feature 分支和 worktree 不变。
