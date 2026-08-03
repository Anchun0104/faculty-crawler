# Faculty Crawler 2.2.0 发布说明

这是 Faculty Crawler 2.2.0 的本地发布候选说明。正式创建 `v2.2.0` GitHub Release 后，再补充公开下载地址和最终 SHA-256；本地构建产物的校验值以本次构建输出为准。

完整版本历史请见 [CHANGELOG.md](CHANGELOG.md)。

## 从 2.1.0 升级后的主要变化

- 将 Windows 桌面端完整重做为 Modern Scientific Utility 风格：浅色科学工具界面、分组导航、页面级标题、低噪声卡片、双栏检查器、运行时间线和一致的输入/表格层级。
- 应用名称、导航、按钮、状态、空状态、弹窗和设置页统一使用简体中文；API、URL、Token、Excel、XLSX、DeepSeek、CAPTCHA 等技术名保持原有写法。
- 重新组织 Overview、Tasks、Manual verification、Run history、Site sessions、Settings/AI、Storage 和 New Crawl 页面，保留原有任务、人工验证、会话、导出和清理逻辑。
- 新建采集对话框同时支持直接粘贴 URL 与导入 XLSX，并对重复 URL、有效数量、学校数量和批次按钮状态提供即时反馈。
- 增加稳定的 UI fixture 和可访问名称，支持在不访问网络、不读取真实任务数据的情况下做真实窗口渲染验收。

## 功能与安全边界

- 采集、快照、官方证据、邮箱解析、review 生命周期和 `run_report.json` 行为沿用 2.1.0；本版本不改变目录发现、AI 或反爬边界。
- 默认仍使用本地确定性规则。外部 AI 必须由用户主动启用并配置 API Key；AI 不生成或替换目录 URL、不猜测邮箱，也不绕过登录、CAPTCHA 或访问控制。
- API Key 继续使用当前 Windows 用户的 DPAPI 保护；Token、Cookie、会话凭据和网页正文不会进入任务文件、Excel、日志或诊断 ZIP。

## 发布验证

- 已通过完整 Python 回归测试：`683 passed, 1 skipped, 190 subtests passed`。
- 已完成真实 PySide6 fixture 窗口验收，覆盖 Overview、Tasks、Manual verification、Run history、Site sessions、Settings/AI、Storage 以及 New Crawl 的 URL/XLSX 模式和 20 条 URL 批量状态。
- 源码 ZIP 使用 `build_release.py` 构建，安装器使用 `build_installer.ps1` 和 D 盘 Inno Setup 6 编译器构建；发布前必须核对构建输出中的提交号、文件名和 SHA-256。

## 本地构建产物

```text
dist/faculty-crawler-windows.zip
dist/faculty-crawler-windows.zip.sha256.txt
dist/installer/FacultyCrawler-Setup-2.2.0.exe
dist/installer/FacultyCrawler-Setup-2.2.0.sha256.txt
```

本次本地构建的安装器 SHA-256：

```text
6D4AAD53698BCF4C65061CE9A4FAB6BBFAB7CA1231DC10F1DAD4BB6A2EB1F5F7
```

本地构建完成后，可用以下命令计算校验值：

```powershell
Get-FileHash .\dist\faculty-crawler-windows.zip -Algorithm SHA256
Get-FileHash .\dist\installer\FacultyCrawler-Setup-2.2.0.exe -Algorithm SHA256
```
