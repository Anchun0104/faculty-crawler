# Title Diagnostics Export Design

## Goal

让人工审核流程可以把 `FacultyCrawler.review_records` 与
`FacultyCrawler.excluded_records` 导出为可复用的 CSV 或 XLSX 文件。

## Scope

导出器只负责把已有 `FacultyRecord` 数据写成结果文件，不改变爬取、分类或翻译行为；不新增远端服务，也不修改默认翻译缓存配置。

## Design

新增独立模块 `crawler/diagnostics_export.py`，提供面向记录列表的导出函数。格式可由显式参数指定，也可从 `.csv` / `.xlsx` 扩展名推断。输出列固定且有稳定顺序：`name`、`title`、`title_translated`、`title_language`、`translation_status`、`translation_engine`、`staff_classification`、`academic_track`、`affiliation_status`、`classification_reason`、`matched_rule`、`confidence_tier`、`source_url`、`profile_url`、`email`、`classification_rules_version`。

CSV 使用 UTF-8 with BOM，便于 Excel 直接打开；XLSX 使用现有 openpyxl 依赖。空记录列表仍写入表头。未知扩展名、缺少扩展名与不支持的显式格式均抛出 `ValueError`；文件系统或序列化错误向调用方传播，避免静默丢失审核数据。

`FacultyCrawler` 增加薄封装方法，分别以 `review_records` 或 `excluded_records` 调用导出器，并允许传入目标路径与可选格式。导出器本身不依赖 crawler 实例，因此可直接测试和复用。

## Testing

新增单元测试覆盖：字段顺序与完整值、Unicode CSV、空列表表头、XLSX 表头和值、扩展名/显式格式判定，以及不支持格式拒绝。Crawler 封装测试使用真实临时文件并确认分别导出对应诊断列表。沿用现有相关回归测试，不宣称受环境限制的全套测试通过。

## Constraints

- 保留当前工作树所有已有未提交改动。
- 不提交、不推送。
- 不删除或覆盖用户文件；目标输出由调用方提供。
