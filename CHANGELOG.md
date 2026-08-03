# 版本变更记录

本文件是功能变更的完整索引。版本状态、下载资产与 Git 标签以对应的 GitHub Release 为准。

## 2.2.0（已发布）

### 新增与改进

- 完整重做 PySide6 桌面端视觉层，采用 Modern Scientific Utility 风格：浅色科学工具主题、分组导航、页面级标题、卡片、双栏检查器、运行时间线和统一的表格/输入层级。
- 应用名称、导航、按钮、状态、空状态、弹窗和设置页统一使用简体中文；API、URL、Token、Excel、XLSX、DeepSeek、CAPTCHA 等技术名保留英文。
- 重做 Overview、Tasks、Manual verification、Run history、Site sessions、Settings/AI、Storage 和 New Crawl 页面，同时保持任务、人工验证、会话、导出、清理和 AI 配置逻辑不变。
- New Crawl 支持 URL/XLSX 双模式的即时校验：重复项、有效数量、学校数量、输出目录和批次按钮状态会随输入更新；多 URL 仍创建一个可恢复的批次任务。
- 增加显式启用的内存 UI fixture、辅助功能名称和真实窗口验收测试，不读取真实任务数据库、不访问网络，也不改变生产默认行为。

### 兼容与安全边界

- 2.1.0 的证据优先采集、快照、PDF/二级来源、邮箱解码、review 生命周期、运行报告和可选 AI 边界保持不变。
- 默认仍为本地确定性规则；AI 不搜索、生成或替换目录 URL，不猜测邮箱，不绕过 CAPTCHA、登录或访问控制。
- API Key 继续由 Windows DPAPI 保护；Token、Cookie、会话凭据和网页正文不会进入任务文件、Excel、日志或诊断 ZIP。

### 发布状态

- 标签：[v2.2.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.2.0)。该 Release 提供 Windows 安装包、源码 ZIP、两个 SHA-256 校验文件和发布说明。
- 安装器 SHA-256：`6D4AAD53698BCF4C65061CE9A4FAB6BBFAB7CA1231DC10F1DAD4BB6A2EB1F5F7`。
- 源码 ZIP SHA-256：`A94F3C6FECC43BD66C1DBD85595AC14FBDDF2B6E459DD6CFA92285A28C4754E3`。
- 完整发布说明见 [RELEASE_NOTES_2.2.0.md](RELEASE_NOTES_2.2.0.md)。

## 2.1.0（已发布）

### 新增

- 将直接 URL 采集和 XLSX 批量采集统一到证据优先后端；普通用户和 Codex/脚本用户共享页面快照、来源处理、邮箱解析、复核和导出能力。
- 支持人工确认的目录入口、官方 HTML/PDF 名录、目录分页/动态展开、官方二级页面及跨页面字段合并。
- 增加轻量且确定性的邮箱解码：处理明确写在页面或页面数据中的受保护/拆分邮箱，不根据姓名生成邮箱。
- 增加可选的 DeepSeek 与 OpenAI Chat Completions 兼容提供方；API key 仅从安全存储或环境变量读取。
- 增加 `run_report.json`，汇总完成情况、失败来源、复核原因、性能、缓存和动态展开信号，供下一轮规则优化使用。

### 改进

- 目录卡片已同时提供姓名、合规职称、学校工作邮箱和字段证据时直接进入 `accepted`，不再访问个人页。
- 目录页保持较稳健的抓取策略；个人页使用单次、快速失败策略，避免少量慢页拖慢整校任务。
- review 只重处理关联学校；无变化的 review 最多自动重处理两次，随后转为 `unresolved`。修复规则、入口或访问条件后可人工重新打开。
- 正式结果只导出 `accepted`；`review_queue.xlsx` 保留 `review` 和 `unresolved`，避免把不够明确的数据写入正式结果。

### 兼容与安全边界

- `directory_url` 必须由用户人工确认。AI 不搜索、生成、替换或猜测目录链接，也不猜测邮箱或成为证据来源。
- 人工提交的实验室/研究所目录可使用不同域名；该目录和其站内页面可作为来源，学校主域名仍用于工作邮箱校验。
- 默认运行本地规则，不调用外部 AI；密钥不写入任务数据库、Excel、报告或日志。

### 发布状态

- 标签：[v2.1.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.1.0)。该 Release 提供 Windows 安装包、源码 ZIP 与对应 SHA-256 校验文件。

## 2.0.0（已发布）

### 新增

- 增加离线多语言职称翻译、缓存和分类，保留原始职称并将不确定情况交给人工复核。
- 发布 Windows 安装包，内置 Playwright Chromium 和离线翻译组件，普通用户无需安装 Python 或 Docker。
- 加强教师目录解析、反爬/会话诊断、任务恢复和 Excel 导出。

### 发布状态

- 标签：[v2.0.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.0.0)。该 Release 保留已验证的安装包、源码 ZIP 及 SHA-256 文件。

## 1.0.0（已归档）

### 新增

- 建立基础高校教师目录采集、Excel 导出、命令行和 Windows 桌面入口。

### 发布状态

- 标签：[v1.0.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v1.0.0)。这是可重建的历史源码锚点；没有可验证的历史安装包资产。
