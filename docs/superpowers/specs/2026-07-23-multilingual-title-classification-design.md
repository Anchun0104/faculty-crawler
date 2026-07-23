# 高校人员多语言职称分类与本地翻译设计

## 1. 目标

在不破坏现有英文高校目录解析能力的前提下，为已经成功抽取到“可信人员 + 原始职位”的记录增加独立分类层。分类层优先使用确定性原文规则；无法判断的非英语职位再调用本机 LibreTranslate 翻译为英语；最终输出 `include`、`exclude` 或 `review`。

数据库用于寻找潜在 keynote speaker、committee member 和 symposium chair，因此收录范围不限于传统全职教学教师。目标人员包括当前在职的教学、科研、临床、实践、博士后、客座、兼职和附属学术岗位。

本功能不解决人员卡片、姓名、职位节点或个人主页链接没有被网页解析器识别的问题。

## 2. 已确认的业务边界

### 2.1 收录

明确收录：

- Professor、Associate Professor、Assistant Professor、Reader；
- Lecturer、Senior Lecturer、Associate Lecturer、University Lecturer；
- Teaching Professor、Teaching Fellow、Instructor；
- Research Professor、Research Fellow、Research Scientist、Principal Investigator；
- Postdoctoral Researcher、Postdoctoral Fellow、Postdoc；
- Clinical Professor、Clinical Lecturer、Clinical Educator；
- Professor of Practice；
- Visiting、Adjunct、Affiliate 学术岗位；
- Doctoral Researcher；
- 各国经过确认的对应外语学术职称。

### 2.2 一票排除状态

只要完整职位、所属人员分区或明确身份字段出现以下状态，即使同时出现当前学术岗位，也一律排除：

- Emeritus / Emerita；
- Honorary；
- Retired；
- Former。

### 2.3 学生和助理岗位

排除：

- PhD Student、Doctoral Student；
- PhD Candidate、Doctoral Candidate；
- Graduate、Master's、Undergraduate Student；
- Teaching Assistant；
- Research Assistant；
- Student Researcher、Research Intern。

`Doctoral Researcher` 单独出现时收录；与 Student、Candidate、Teaching Assistant 等排除身份共同出现时排除。

### 2.4 专业服务和技术岗位

以下岗位族不收录：

- 图书馆、档案、馆藏和开放获取服务；
- IT、ICT、数据平台、软件开发和数字服务；
- 实验室技术、仪器、核心设施和科研技术支持；
- 行政、运营、项目管理和秘书；
- 教务、招生、注册、课程和学生支持；
- 人力资源、财务、采购、合同、法务和合规；
- 市场、传播、出版、活动、校友和筹款；
- 设施、物业、安全、后勤和餐饮；
- Research Software Engineer、Scientific Programmer、Research Data Scientist、Bioinformatician、Biostatistician 等科研专业技术岗位。

规则必须使用完整短语或明确组合，不得用 `assistant`、`manager`、`officer`、`engineer`、`scientist`、`technology`、`library` 等单词做全局排除。

### 2.5 医疗岗位

Clinical Professor、Clinical Associate/Assistant Professor、Clinical Lecturer 等明确学术职位收录。

Consultant、Physician、Surgeon、Clinician、Pharmacist、Nurse 等仅有临床职位而没有明确高校学术任职时进入 `review`。

## 3. 选择的架构

采用“解析后独立分类层”：

```text
HTML 解析
→ 可信人员候选与原始职位
→ 原文确定性分类
→ 未知非英语职位调用本地翻译
→ 翻译结果再次分类
→ include / exclude / review
→ 分工作表导出
```

不在 `crawler/parsers.py` 的人员卡片解析分支中发起翻译请求。解析器负责页面结构和字段抽取；分类器负责业务判断；翻译客户端只负责本地翻译。

现有解析阶段中妨碍非英语可信职位进入分类层的过早过滤，将通过小范围、带回归测试的改动逐项迁移，不进行无关重构。

## 4. 模块边界

### 4.1 `crawler/title_classifier.py`

负责：

- Unicode、大小写、标点和空白规范化；
- 原文多语言短语匹配；
- 英文职位短语分类；
- 组合职位冲突处理；
- `include`、`exclude`、`review` 输出；
- `academic_track`、`affiliation_status`、命中规则和理由；
- 分类规则版本。

不负责网络请求、HTML 解析或 Excel 写入。

### 4.2 `crawler/translation.py`

负责：

- 检查 `http://127.0.0.1:5000`；
- 查询 `/languages`；
- 调用 `/translate`；
- 连接超时、响应超时、一次重试和响应校验；
- SQLite 翻译缓存；
- 返回结构化翻译状态。

不负责判断人员是否应收录。

### 4.3 现有模块

- `crawler/parsers.py`：继续负责候选边界、姓名、原始职位、个人主页和邮箱；
- `crawler/faculty_crawler.py`：在解析结果之后调用分类层，并负责输出聚合；
- CLI 和桌面应用：配置是否启用本地翻译、展示服务状态和运行统计；
- Excel 导出：写入 Faculty、Review、Excluded 和 Run Summary。

## 5. 数据模型

分类后的记录至少保留：

- `name`；
- `title_original`；
- `title_translated`；
- `title_language`；
- `profile_url`；
- `email`；
- `staff_classification`；
- `academic_track`；
- `affiliation_status`；
- `classification_reason`；
- `matched_rule`；
- `confidence_tier`；
- `translation_status`；
- `translation_engine`；
- `classification_rules_version`；
- `source_url`。

官网原始职位永远保留。译文不得覆盖原文。

置信层级为可解释的离散值：

- `high`：确定性原文或完整短语；
- `medium`：翻译后的确定性完整短语；
- `low`：模糊职位、规则冲突或上下文不足。

不把该字段表达成未经校准的概率。

## 6. 分类优先级

固定顺序：

1. 一票排除状态；
2. 学生、Candidate、Teaching/Research Assistant；
3. 明确专业服务和技术岗位；
4. 明确学术职位；
5. 模糊职位；
6. 无匹配结果。

完整短语先于单词边界规则；原文规则先于翻译；排除规则先于收录规则。

示例：

```text
Doctoral Researcher                         → include
Doctoral Researcher / PhD Candidate         → exclude
Research Support Officer                    → exclude
Research Fellow                             → include
Academic Librarian                          → exclude
Professor of Library Science                → include
Assistant Professor                         → include
Research Director                           → review
Research Director and Professor             → include
Emeritus Professor and Research Director    → exclude
```

当前代码中损坏的 Unicode 规则（例如乱码的加泰罗尼亚语职称）必须修复并添加编码回归测试。

## 7. 本地翻译设计

LibreTranslate 作为独立可选服务运行，推荐使用固定版本 Docker 容器，不与主爬虫的 Python 3.14 环境混装。

默认只允许：

```text
http://127.0.0.1:5000
```

第一版不自动调用官方或其他公共托管实例。

翻译触发条件：

1. 人员和非空职位已可信抽取；
2. 原文规则不能明确分类；
3. 本地服务可用；
4. 语言模型可用；
5. 缓存没有相同结果。

仅翻译职位，不翻译姓名、院系、简介、研究方向或整个页面。

语言判断优先使用已知词典、HTML/页面语言和 Unicode 文字系统；仍不确定时使用 LibreTranslate 自动检测。

默认故障策略：

- 连接超时 2 秒；
- 响应超时 10 秒；
- 自动重试一次；
- 服务未启动、超时、不支持语言、无效响应或翻译失败均进入 `review`；
- 翻译故障不得使整个抓取任务失败。

## 8. 缓存和 C 盘空间

使用 Python 标准库 `sqlite3`，不新增缓存依赖。默认缓存位于：

```text
%LOCALAPPDATA%\FacultyCrawler\translation_cache.sqlite3
```

缓存键包含规范化原文、源语言、目标语言、翻译引擎和版本。缓存是可重建资产，不进入 Git。

考虑 C 盘空间优先，实施时必须：

- 记录缓存大小和位置；
- 提供安全的缓存清理入口；
- 不把语言模型或 Docker 数据复制进项目仓库；
- 文档说明 Docker 镜像、数据卷和模型可能占用 C 盘；
- 支持用户将 Docker 数据位置迁移到其他磁盘的说明，但不由程序自动修改 Docker 全局设置；
- 不下载未使用的全部语言模型，只安装项目实际需要的语言；
- 构建包排除 `.venv`、缓存、日志、模型和 Docker 数据。

## 9. 桌面应用

增加：

```text
☑ 启用本地职位翻译
服务状态：已连接 / 未启动 / 缺少语言模型
```

默认启用检测，但未检测到服务时不阻断抓取。界面提示未知外语职位将进入待复核结果。

第一版提供“检查服务”，不自动安装 Docker，不自动下载模型，不修改 Docker 全局存储配置。

## 10. Excel 输出和人工复核

### 10.1 `Faculty`

只包含明确 `include`，保留原始职位、译文、语言、学术轨道、分类理由、翻译状态和来源。

### 10.2 `Review`

包含模糊职位、翻译服务不可用、不支持语言、翻译失败、无规则命中和冲突职位。增加：

- `Manual_Decision`；
- `Manual_Note`。

### 10.3 `Excluded`

包含明确排除项和排除类别，便于抽查误排：

- inactive or honorary；
- student or assistant；
- administrative；
- library；
- IT；
- technical；
- other professional services。

### 10.4 `Run Summary`

记录候选、收录、排除、复核、原文命中、翻译调用、缓存命中、失败、不支持语言、规则版本和服务状态。

人工判断不会自动改写核心规则。复核结果先生成候选规则，经测试和确认后才合并。

## 11. 测试和验收

### 11.1 分类器

覆盖所有确认的收录、排除、组合优先级、模糊岗位和 Unicode 外语职称。特别验证：

- `Assistant Professor` 不被 `assistant` 误伤；
- `Professor of Library Science` 不被 `library` 误伤；
- `Research Support Officer` 不因 `research` 被收录；
- `Doctoral Researcher` 与组合排除规则；
- Emeritus/Honorary/Retired/Former 一票排除。

### 11.2 翻译客户端

自动化测试使用假服务，不依赖真实 Docker。覆盖可用、未启动、超时、无效响应、不支持语言、缓存命中和失败降级。

### 11.3 解析器

每次调整遵守 `CODEX_PARSER_RULES.md`：一个正向测试、一个现有结构回归测试、一个防止行政或导航内容被误收录的负向测试。

### 11.4 导出和端到端

验证分表、原文保存、分类理由、统计、重复记录、无翻译服务运行和现有入口兼容。

完成标准：

- 所有现有和新增测试通过；
- 未知非英语职位不会静默删除；
- 明确专业服务岗位不会进入 Faculty；
- LibreTranslate 未启动时程序仍能完成抓取；
- 缓存、模型、人员数据和敏感信息不进入 Git；
- 新电脑能够按文档恢复并完成真实抓取与本地翻译。

## 12. GitHub 和跨电脑移交

代码、规则、测试、Docker 配置、文档和示例配置进入 `codex/translation` 分支，完成验证后推送并创建 draft PR。

不进入 GitHub：

- 人员抓取结果；
- Cookie、Token、API key；
- 本地翻译缓存；
- Docker 数据卷和语言模型；
- 虚拟环境、浏览器缓存和运行日志。

移交包包含：

```text
handoff/
├─ HANDOFF.md
├─ progress.json
├─ reviewed_titles.xlsx       # 有真实复核数据时，可选且不得提交公共仓库
├─ custom_title_rules.json    # 有未合并规则时，可选
└─ translation_cache.sqlite3  # 可选、可重建
```

新电脑恢复顺序：

1. 安装 Git、Python 和 Docker Desktop；
2. clone 仓库并 checkout `codex/translation`；
3. 阅读 HANDOFF.md 和本设计；
4. 安装项目依赖和 Playwright；
5. 启动固定版本 LibreTranslate 并安装所需模型；
6. 运行完整测试；
7. 完成一次真实抓取和本地翻译；
8. 确认 Excel 输出与缓存正常。

每次停止开发前更新移交说明、完成/未完成任务、最后测试结果、分支和 commit SHA。

## 13. 旧电脑清理

只有新电脑完成上述验收后，旧电脑才能进入清理阶段。

先生成 `handoff-cleanup-manifest.json`，逐项记录：

- 绝对路径或 Docker 资源名称；
- 用途和占用空间；
- 是否已经迁移；
- 是否可以重建；
- 建议保留或删除；
- 实际清理时间。

可清理的项目专用内容：

- `%LOCALAPPDATA%\FacultyCrawler` 下的缓存和非必要日志；
- 本项目专用 LibreTranslate 容器、镜像、数据卷和模型；
- 项目 `.venv`；
- `__pycache__`、`.pytest_cache`；
- 临时诊断文件和被新版替代的旧移交包。

不得自动清理：

- Docker Desktop、Python、Git；
- 全部 Docker 镜像、容器或数据卷；
- 全局 Playwright 浏览器，除非确认无其他项目使用；
- 用户整个 AppData、Downloads、用户目录或磁盘根目录；
- GitHub 凭据；
- 其他项目资产；
- 当前仓库和最终移交包，直到用户明确确认。

实际删除前必须向用户展示准确目标、大小和用途，并再次取得确认。清理操作不得与普通安装、抓取或移交命令绑定。

## 14. 实施顺序

1. 建立分类数据契约和纯规则分类器；
2. 补齐、修正多语言和专业服务规则；
3. 建立本地翻译客户端和 SQLite 缓存；
4. 在解析后集成三态分类；
5. 扩展 Excel 分表和运行统计；
6. 增加 CLI/桌面配置与服务状态；
7. 增加 Docker 配置和文档；
8. 完成全量回归、真实小样本验证和 C 盘占用检查；
9. 更新 GitHub 分支、draft PR 和移交包；
10. 新电脑验收后，按清理清单处理旧电脑项目专用缓存。

