# Local Translation Settings Design

## Goal

让桌面程序和 CLI 能配置本机 LibreTranslate 的 endpoint、缓存路径、连接超时、响应超时与重试次数，同时保持翻译器接口稳定并拒绝任何非本机 endpoint。

## Scope

本阶段实现配置数据、持久化迁移、CLI 覆盖和 crawler 注入。不下载模型、不启动子进程、不打包 LibreTranslate；这些属于后续的本机服务管理和离线发布阶段。也不接入 DeepSeek 或其它远程 AI。

## Architecture

新增不可变 `TranslationSettings`，默认值与当前 `LibreTranslateClient` 行为一致：`http://127.0.0.1:5000`、默认用户缓存目录、2 秒连接超时、10 秒响应超时、1 次重试、英语目标语言。配置验证复用同一 loopback 规则：只允许 `localhost`、`127.0.0.1` 或 `::1`，并拒绝携带用户名、密码、查询或 fragment 的 URL。

`TranslationSettings.create_client()` 创建 `TranslationCache` 和 `LibreTranslateClient`；`FacultyCrawler` 增加可选 `translation_settings` 参数，仅在没有显式注入 `title_pipeline` 时使用它。这样 `TitlePipeline` 的翻译器注入接口不变，后续其它翻译实现可独立接入。

现有 `AppSettings` 添加翻译设置字段，但 `SettingsStore.load()` 接受旧三字段 JSON 并补全默认值，避免升级后丢失用户设置。桌面“高级设置”显示本机 endpoint、缓存路径与超时/重试；CLI 允许同名参数覆盖默认值或已保存配置，不把远端地址放宽为可选项。

## Error Handling

无效 endpoint、非正超时、负重试和空缓存路径在保存/解析时返回明确错误。翻译服务不可用仍由现有 pipeline 返回 `service_unavailable` 并进入 REVIEW，不中断抓取。

## Tests

测试默认值、loopback URL 允许/拒绝、旧 settings 文件迁移、原子持久化、CLI 参数传递、crawler 使用注入设置且显式 title pipeline 优先。保留现有本机 endpoint 安全测试。

## Constraints

- 只允许本机翻译 endpoint。
- 不添加远程 AI、DeepSeek、API key 或网络凭据。
- 保留 `TitlePipeline` 的翻译器注入接口。
- 保留当前未提交改动；不提交、不推送。
