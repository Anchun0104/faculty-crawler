# AI / Codex 脚本工作流

本说明面向使用 Codex、其他 AI 编排工具或命令行批量运行的用户。它与 Windows 安装包的普通用户界面是两条入口，但共用同一套 `WorkflowService`、页面快照、官方证据、邮箱解析、复核队列和审计导出。

## 安全边界

- 每个学校的 `directory_url` 必须由人工确认；AI 不搜索、生成、替换或猜测目录链接。
- AI 只可解析已抓取的页面、辅助专业判断；不能猜测邮箱，也不能充当证据来源。
- 空邮箱、冲突邮箱或来源不足的记录会留在 `review_queue.xlsx`，不会写进正式结果。
- 脚本从环境变量读取 API key，不接受 key 命令行参数；请不要把 key 写入 XLSX、任务 JSON 或日志。

人工提交的实验室或研究所目录可以使用与学校主域名不同的域名；该目录及其站内页面作为可信来源，学校主域名仍用于工作邮箱校验。

## 运行方式

先安装依赖：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 直接 URL

默认本地规则，不调用外部 AI：

```powershell
.\.venv\Scripts\python.exe workflow.py url `
  --output-dir .\output\example `
  --school "Example University" `
  --discipline "Physics" `
  https://example.edu/physics/faculty
```

可提供多个 URL；多个 URL 时系统会按 URL 域名生成学校标识，不能同时传单个 `--school` 覆盖名。

### XLSX 批量任务

学校表必须含 `school`（或 `university`）和 `directory_url` 列。创建任务后先确认专业口径，再运行：

```powershell
.\.venv\Scripts\python.exe workflow.py new `
  --schools .\schools.xlsx `
  --discipline "Physics" `
  --output-dir .\output\physics `
  --no-model

.\.venv\Scripts\python.exe workflow.py policy --task <TASK_ID> --file .\policy.json --confirm
.\.venv\Scripts\python.exe workflow.py run --task <TASK_ID>
.\.venv\Scripts\python.exe workflow.py export --task <TASK_ID>
```

导出包括兼容结果 Excel、`completed_evidence.xlsx`、`review_queue.xlsx` 和 `audit.json`。

## 启用兼容 AI

不传 `--ai-provider` 时脚本不会使用模型。API key 仅从环境变量读取；可以换成团队约定的变量名。

DeepSeek 示例：

```powershell
$env:FACULTY_CRAWLER_API_KEY = "your-key"
.\.venv\Scripts\python.exe workflow.py `
  --ai-provider deepseek `
  --ai-model deepseek-v4-flash `
  url --use-ai --output-dir .\output\example https://example.edu/faculty
```

任意 Chat Completions 兼容服务（如具备公开兼容 API 的 GPT、豆包兼容端点）示例：

```powershell
$env:TEAM_MODEL_KEY = "your-key"
.\.venv\Scripts\python.exe workflow.py `
  --ai-provider compatible `
  --ai-base-url https://gateway.example/v1 `
  --ai-model your-model-name `
  --ai-key-env TEAM_MODEL_KEY `
  url --use-ai --output-dir .\output\example https://example.edu/faculty
```

兼容端点必须支持 `POST /chat/completions` 和 JSON object 输出。没有公开兼容 API 的客户端（例如仅有桌面产品的 AI）应由 Codex/脚本适配层调用，不能假装成安装包内置模型。

## 复核与重处理

```powershell
.\.venv\Scripts\python.exe workflow.py review --task <TASK_ID>
.\.venv\Scripts\python.exe workflow.py reprocess-reviews --task <TASK_ID>
```

`reprocess-reviews` 只重新处理 review 关联的学校，已完成的 accepted 记录会保留。

## 快速模式、未解决记录与优化报告

目录页已具备姓名、学校工作邮箱、合规职称和字段证据的人员会直接进入 `accepted`，不会访问个人主页。只有证据不足的人员才访问个人页，并使用默认 `10 秒 / 1 次` 的快速失败策略。

正式结果只含 `accepted`。`review_queue.xlsx` 包含 `review` 和 `unresolved`；后者是自动重处理的终态，不会写入正式结果。review 最多重处理两次，若证据和原因无变则会提前变为 `unresolved`。升级解析规则、修复专页适配或完成访问验证后，再人工重新运行该学校。

导出为正式结果 Excel、`review_queue.xlsx` 和 `run_report.json`。让 Codex 优化时，提供 `run_report.json` 并要求其先根据 `optimization_signals`、失败页与复核原因统计识别瓶颈，再提出修改。该报告不包含 API key、Cookie、页面正文或模型提示词。
