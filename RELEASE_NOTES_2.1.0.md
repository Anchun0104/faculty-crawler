# Faculty Crawler 2.1.0 发布说明

## 主要更新

- 新增证据优先的院校教师采集工作流，支持任务数据库、政策确认、候选复核、证据导出和审计记录。
- 新增 `local-only` 模式，可在不调用 DeepSeek 等外部模型的情况下运行官方目录采集。
- 支持官方 HTML 与 PDF 名录、已抓取快照缓存和确定性重处理。
- 扩展官方二级来源发现，可识别 staff、faculty、research group、research portal 等入口。
- 支持复核候选单独重处理，并保留被替代记录的审计轨迹。
- 加强院系边界控制，避免从目标院系跳转到兄弟院系。
- 加强非人员内容过滤，排除栏目标题、项目导航、公共联系块、管理和技术支持页面。
- 个人主页中的明确姓名、职称和邮箱优先于错误或含糊的目录标签。
- 发布源码包现包含 `faculty_workflow`、工作流入口、验证脚本和完整测试。

## 主要入口

- 原桌面程序：`desktop_app.py`
- 证据工作流命令行：`workflow.py`
- 证据工作流桌面入口：`workflow_desktop.py`
- 接受结果校验：`python -m scripts.validate_task_acceptance <database> <task_id>`

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall crawler faculty_workflow scripts workflow.py workflow_desktop.py
git diff --check
```

## 数据安全

源码发布包不包含 `workflow_data`、SQLite 数据库、抓取快照、生成的 Excel、日志、虚拟环境或 Codex 会话文件。
