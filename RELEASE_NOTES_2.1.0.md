# Faculty Crawler 2.1.0 发布说明

本版本对应 [v2.1.0 Release](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.1.0)。Release 附带 Windows 安装包、源码 ZIP 以及各自的 SHA-256 校验文件。

完整版本历史请见 [CHANGELOG.md](CHANGELOG.md)。

## 从 2.0.0 升级后新增的能力

- 直接 URL 和 XLSX 批量输入改为共享同一证据优先后端；普通本地用户、Codex 和脚本用户得到一致的快照、来源、邮箱、复核与导出行为。
- 支持人工确认的官方目录入口、HTML/PDF 名录、分页和动态目录展开，以及目录链接出的官方二级页面。
- 姓名、职称和工作邮箱通过已抓取的官方页面确认；轻量解码仅恢复页面中明确存在的受保护/拆分邮箱，不根据姓名猜测邮箱。
- 可选支持 DeepSeek 和 OpenAI Chat Completions 兼容服务。默认仍为本地规则，API key 不写入任务数据库、Excel、报告或日志。

## 速度与访问策略

当目录卡片已提供姓名、合规职称、学校工作邮箱和对应字段证据时，系统会直接收录为 `accepted`，跳过个人主页。只有证据不足、专业归属不明确或字段冲突的候选才访问个人页。

目录页使用较稳健的抓取与展开策略；个人页默认单次尝试、10 秒快速失败。慢页和坏页会进入复核，不再将几十秒的多次重试放大为整校任务的长时间停滞。

## review、未解决记录与重新处理

正式结果 Excel 只包含 `accepted`。`review_queue.xlsx` 包含仍可自动重试的 `review` 和终止自动重试的 `unresolved`；两者都不会混入正式结果。

review 重新处理只会运行本次 review 关联的学校。若来源、证据与复核原因均无变化，最多自动重新处理两次后会转为 `unresolved`，避免无意义的持续爬取。更新邮箱解码规则、修复网站适配、修正入口 URL 或完成访问验证后，可人工填写原因并重新打开 `unresolved` 记录；原有 `accepted` 记录不会被覆盖。

## 运行报告与后续优化

每次任务完成会导出 `run_report.json`。它不保存页面正文、Cookie、API key 或模型提示词，而是汇总结果、失败来源、复核原因、抓取耗时、重试、缓存命中、动态展开动作和停止原因。

下一轮使用 Codex 优化时，应先检查 `outcomes`、`diagnostics.failed_sources`、`top_review_reasons`、`optimization_signals` 和 `performance`，再判断是调整超时策略、补邮箱解码、增加页面适配还是修复来源边界。

## 发布验证

- 完整单元测试、Python 编译检查和源码 ZIP 内容检查通过。
- Windows 安装器已从本版本候选提交重新构建，并确认包含旧爬虫、`faculty_workflow.service` 和 `pypdf`。
- 安装器 SHA-256 以 Release 中的 `FacultyCrawler-Setup-2.1.0.sha256.txt` 为准；源码 ZIP SHA-256 以 `faculty-crawler-windows.sha256.txt` 为准。
- 真实 Windows UI、安装与卸载 smoke test 仍建议在最终使用环境完成。
