# 高校教师信息采集工具

这是一个面向高校院系教师目录的 Python 数据采集工具。它可以从公开的教师目录页面中识别教师姓名、职称和个人主页地址，并将结果导出为 Excel。项目同时提供命令行入口和 Windows 桌面端，适合单个页面采集、批量任务、人工验证和失败诊断。

本项目采用保守、合规的访问策略：不自动破解 CAPTCHA，不绕过登录、付费墙或访问控制，不使用代理池、浏览器指纹伪装或高频请求规避封禁。使用者应遵守目标网站的服务条款、robots 规则以及适用的法律法规。

## 版本演进

| 版本 | 状态与定位 | 主要增加内容 |
| --- | --- | --- |
| [v1.0.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v1.0.0) | 已归档的源码基线 | 基础目录采集、Excel 导出和桌面/命令行入口；没有可验证的历史安装包，但可从该标签重建。 |
| [v2.0.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.0.0) | 当前稳定安装包版本 | 离线多语言职称翻译与分类、人工复核、内置 Chromium 和离线翻译组件。 |
| [v2.1.0](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.1.0) | 当前正式版本 | 统一直接 URL 与 XLSX 任务、官方证据和快照、PDF/二级页面、轻量邮箱解码、快速路径、有限 review、运行报告和可选兼容 AI。 |

完整的逐版本功能记录请见 [CHANGELOG.md](CHANGELOG.md)。2.1.0 的安装包、源码包和 SHA-256 校验文件均附在 [v2.1.0 Release](https://github.com/Anchun0104/faculty-crawler/releases/tag/v2.1.0)。

### 选择使用方式

- **普通本地用户**：下载当前稳定版 Windows 安装包，直接在图形界面输入目录 URL，或切换到批量 XLSX 工作流。
- **Codex、脚本或模型编排用户**：阅读 [README_WORKFLOW_AI.md](README_WORKFLOW_AI.md)，使用同一证据工作流的 URL/XLSX 命令入口。

两种方式均由用户提供可信的 `directory_url`。AI 只能辅助解析已经抓取的页面和专业判断，不能发现/替换目录 URL、猜测邮箱或充当证据来源。

## 已实现的主要功能

### 数据采集与清洗

- 接收一个或多个高校教师目录 URL。
- 使用 Playwright Chromium 加载静态页面和 JavaScript 动态页面。
- 提取教师姓名、学术职称和个人主页 URL。
- 解析相对链接并规范化个人主页地址。
- 按个人主页 URL 去重，并清理常见跟踪参数。
- 将结果导出为 `.xlsx`，主要字段为 `Name`、`Title` 和 `Profile_URL`。
- 对姓名明确但职称不可靠的记录单独输出“职称待确认”文件，避免把不确定结果混入正式数据。
- 检测结果覆盖率过低、没有候选记录等异常情况，并给出诊断信息。

### 批量任务与恢复

- 支持一次输入多个目录 URL，并按顺序执行。
- 自动生成合法且不重复的 Excel 文件名，避免覆盖已有结果。
- 保存任务状态，程序中断后可以恢复未完成任务。
- 支持“完成当前任务后停止”，剩余任务不会被误标记为失败。
- 对成功、失败、需要人工验证、建议复核和已停止等结果分别记录。

### 桌面端工作流

- 单一 `FacultyCrawler.exe` 提供“直接 URL 采集”和“批量证据工作流”两种入口；两者共享快照、邮箱解析、复核和导出能力。
- 提供首页、任务列表、人工验证、会话、运行记录和设置页面。
- 可查看任务状态、失败阶段和经过脱敏的诊断信息。
- 支持单项或顺序处理人工验证任务。
- 支持管理已保存的站点会话。
- 支持生成隐私安全的问题报告 ZIP。
- 支持设置默认输出目录、任务超时和飞书共享文件夹链接。
- Windows 安装包内置 Chromium 和离线多语言职称翻译服务；目标电脑无需预先安装 Python、Docker 或翻译软件。
- 翻译服务仅监听本机回环地址，应用启动时自动管理，退出应用后自动停止。
- 支持阿拉伯语、简体/繁体中文、荷兰语、法语、德语、意大利语、日语、葡萄牙语和西班牙语职称翻译为英语；翻译失败会保守进入人工审核。

### 离线翻译组件

2.0.0 起，Windows 发行包会在主程序目录中携带 `translation-service` 子目录及必要的 Argos 模型。用户只需安装或解压一个包并启动主程序；不需要单独安装或运行 LibreTranslate。首次打开应用时，服务会在本机加载模型，随后由程序在后台使用。该组件采用 LibreTranslate（AGPL-3.0），详见 `THIRD_PARTY_NOTICES.md`。

## 当前能够处理的网页结构

解析器并不依赖某一个学校的固定 HTML 模板，而是通过受约束的启发式规则识别常见高校教师目录结构。

### 常见内容布局

- 重复出现的教师卡片、人物卡片和个人简介卡片。
- 教师姓名与职称分别位于标题、段落、列表项或相邻元素中的页面。
- 姓名、职称和主页链接位于同一表格行的目录。
- 一个表格单元格中包含多名教师的紧凑型列表。
- 按教授、研究人员或学术岗位分组的列表。
- 手风琴、折叠面板和按角色分组的人员目录。
- 只有人物姓名链接、职称位于链接前后文本中的页面。
- 个人主页链接指向同一高校的其他子域，或卡片内可信的外部学术主页。
- 使用查询参数区分不同人员、但路径相同的个人主页。

### 动态加载结构

- JavaScript 首次渲染的教师目录。
- 普通“下一页”分页。
- 页码或查询参数分页。
- 页面大小选择器。
- `Load more` /“加载更多”按钮。
- 页面整体滚动加载。
- 内部滚动容器加载。
- 虚拟列表；采集过程中会保留发生变化的页面快照并合并结果。

### 内容过滤和边界控制

- 优先在主要内容区和重复的人物容器中提取信息。
- 排除导航栏、页脚、隐私政策、普通新闻和组织介绍链接。
- 识别并排除部分行政人员、荣休人员或明显不属于目标教师范围的分组。
- 防止姓名、职称和主页跨卡片或跨表格行错误拼接。
- 对只有通用“Profile”“Website”等链接文字的页面，尝试从同一卡片标题提取姓名。
- 不将登录页、验证码页、禁止访问页或空页面误当作教师目录。

由于高校网站结构差异非常大，上述能力表示“已有对应策略”，不代表能够无配置地正确解析所有网站。

## 反爬、登录和异常处理

- 识别普通页面、登录页、验证码/挑战页、禁止访问页、限流页和服务器错误页。
- 对 `429`、部分 `5xx`、页面加载超时等临时错误执行有上限的保守重试。
- 支持 `Retry-After`，并使用退避和同域串行降低访问压力。
- 不对所有 `403` 盲目重试；会根据页面信号区分临时状态、人工验证和不可恢复拒绝。
- 在必须人工操作时打开可见浏览器，由用户自行完成合法验证。
- 验证成功后，只按精确主机保存可复用会话，不跨站点共享。
- Windows 会话数据使用 DPAPI 保护，并按保留期限清理。
- Cookie、密码、Token、Authorization、会话字节和网页正文不会进入任务文件或问题报告。

以下情况不会由脚本自动“解决”：

- 账号没有访问权限。
- 网站仅允许校园网、指定 VPN、地区或白名单 IP。
- 站点明确禁止自动访问。
- 必须破解 CAPTCHA、伪造浏览器指纹或绕过高级 WAF 才能进入。
- 内容位于付费墙、授权系统或其他访问控制之后。

## 安装与使用

### Windows 普通用户

发布给同事时，优先使用 GitHub Releases 中的 [FacultyCrawler-Setup-2.1.0.exe](https://github.com/Anchun0104/faculty-crawler/releases/download/v2.1.0/FacultyCrawler-Setup-2.1.0.exe)。安装包包含桌面程序、Playwright Chromium 与离线翻译服务，正常使用不需要 Python、命令行、Docker 或管理员权限。

当前安装包没有商业代码签名，因此 Windows SmartScreen 可能显示“未知发布者”。安装前应确认文件来自本项目的 GitHub Release，并核对版本说明中的 SHA-256。

### 从源码运行

需要 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

命令行采集示例：

```powershell
python main.py "https://www.eecs.mit.edu/people/faculty-advisors/" --output "output/mit_faculty.xlsx"
```

可选参数：

```powershell
python main.py <教师目录URL> --output <输出文件.xlsx> --timeout 30000 --verbose
```

Windows 源码模式也可以先运行一次 `setup.bat`，之后双击 `start.bat` 启动桌面端。

## 版本管理

项目根目录的 `VERSION` 是唯一版本来源，当前版本为 `2.1.0`。升级版本时只需修改该文件，例如从 `2.1.0` 改为 `2.2.0`；构建脚本会把版本同步写入桌面程序、安装器元数据和安装包文件名。

每次构建完成后，脚本会输出版本号、Git 提交号以及安装包 SHA-256，便于同事确认拿到的是同一个版本。

## 构建发布文件

生成干净的 Windows 源码包：

```powershell
python build_release.py
```

生成文件位于 `dist/faculty-crawler-windows.zip`。发布脚本会排除虚拟环境、测试缓存、历史输出和 Git 元数据。

构建桌面程序和安装包需要：

- 64 位 Python 3.11 或更高版本；
- 构建时可以下载依赖和 Playwright Chromium；
- Inno Setup 6；
- `requirements-build.txt` 中声明的构建依赖。

构建过程会把虚拟环境、浏览器、模型和 PyInstaller 中间文件放入系统临时构建目录，避免 Chromium 的深层目录触发 Windows 路径长度限制；最终安装包仍写入 `dist/installer/`。

执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

也可以显式指定 Python 和 Inno Setup：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1 `
  -PythonExecutable "C:\Path\To\python.exe" `
  -InnoCompiler "C:\Path\To\ISCC.exe"
```

成功后生成：

```text
%TEMP%/FacultyCrawler-installer-build/dist/FacultyCrawler/FacultyCrawler.exe
dist/installer/FacultyCrawler-Setup-2.1.0.exe
```

## 运行测试

使用 Codex、其他 AI 编排工具或命令行批量执行证据工作流，请阅读 [README_WORKFLOW_AI.md](README_WORKFLOW_AI.md)。Windows 安装包继续面向普通用户的一键本地使用。

安装运行依赖和 Chromium 后执行：

```powershell
python -m unittest discover -s tests -v
```

桌面端仍应在 Tcl/Tk 正常的 Windows 环境中完成真实窗口、Chromium、Excel 导出、安装和卸载 smoke 测试。无窗口测试不能完全替代最终 UI 验收。

## 多语言职称分类开发进度

2.0.0 已完成多语言职称分类、翻译和人工复核闭环：

- 建立可审计的 `include`、`exclude`、`review` 三态结果模型；
- 支持 Unicode 职称规范化；
- 增加教学、研究、临床、实践、客座、兼职、博士后、Doctoral Researcher 及部分非英语学术职称规则；
- 优先排除荣休、荣誉、退休、前任、学生、助教/助研、图书馆、IT、实验技术、行政和其他专业服务岗位；
- 使用完整短语和“更长规则优先”，避免因 `assistant`、`library` 等单词误伤 `Assistant Professor` 或 `Professor of Library Science`；
- 确定性规则无法识别时，使用本机 LibreTranslate 将支持的非英语职称翻译为英语；翻译结果使用 SQLite 缓存，并保留原文、译文、语言、翻译状态和分类原因；
- `include` 记录进入正式 Excel，`exclude` 和 `review` 记录会分别导出，便于人工审核和补充精确原文规则。

翻译服务仅限本机回环地址；它是桌面程序自带的离线组件，不向第三方发送网页内容。后续如加入 AI 页面结构解析，会作为独立、可选的 fallback，不与当前翻译服务耦合。

## 当前缺陷与限制

### AI 为可选辅助，不参与目录发现

2.1.0 的脚本和桌面端默认使用本地确定性规则；用户只有主动启用并配置兼容模型后，才会调用外部 AI。AI 仅可处理已抓取页面的结构化解析、专业判断和政策草案，不能生成/替换目录 URL、猜测邮箱或作为正式证据。

因此，默认运行没有模型费用，也不会把网页内容发送给第三方。即使启用 AI，最终 `accepted` 记录仍必须具有足以自动确认的官方页面字段证据；不充分或冲突的数据会进入 review，而非被模型猜测补齐。

### 解析和网站变化

- 启发式解析不能保证覆盖所有高校网站。
- 网站改版、CSS 类名变化或动态接口调整可能使已有规则失效。
- 复杂 Shadow DOM、Canvas 渲染、嵌套 iframe 或专有前端组件可能无法提取。
- 页面能显示人物不代表能够可靠判断其职称或教师身份。
- 多语言职称词汇和组织结构仍可能产生漏采或误分类。

### 反爬和访问权限

- 长期 IP 封禁、地区限制、校园网限制和账户权限问题不能由脚本解决。
- 高级 WAF 或必须自动破解 CAPTCHA 的页面不会被绕过。
- 保存的会话只适用于完成验证的精确主机，并可能随站点策略变化而失效。

### 发布与验收

- Windows 安装包目前没有商业代码签名。
- GitHub 仓库不保存历史 Excel 结果或浏览器运行时；面向用户的安装包通过 GitHub Releases 发布。
- 真实 Windows UI 和安装流程仍需在目标电脑上做最终验收。

## 后续计划

以下内容是规划方向，不代表已经实现：

1. 完善 `403` 诊断，将失败稳定区分为“可恢复”“需人工”和“不可脚本解决”。
2. 增加更多可复现的高校页面样本和解析回归测试。
3. 建立 GitHub Actions，在 Pull Request 中自动运行测试。
4. 将 Windows 安装包改为按版本标签自动构建并上传到 GitHub Releases。
5. 持续完善可选 AI 的页面解析质量、最小化发送内容和兼容端点测试；AI 不用于目录发现、邮箱猜测、CAPTCHA、登录或访问控制绕过。
6. 扩充多语言职称词典和院系角色分类。
7. 完善安装包签名、版本升级和发布校验流程。

## 项目结构

```text
.
├── crawler/                 # 采集、解析、任务、诊断、会话和隐私逻辑
├── ui/                      # Windows 桌面界面
├── tests/                   # 单元测试与工作流测试
├── installer/               # Inno Setup 配置
├── docs/                    # 设计和实施文档
├── main.py                  # 命令行入口
├── desktop_app.py           # 桌面端入口
├── VERSION                  # 唯一版本号来源
├── requirements.txt         # 运行依赖
├── requirements-build.txt   # 构建依赖
├── build_release.py         # 源码发布包构建
└── build_installer.ps1      # Windows 安装包构建
```

## GitHub 协作方式

首次获取代码：

```powershell
git clone https://github.com/Anchun0104/faculty-crawler.git
cd faculty-crawler
```

每项修改建议使用独立分支：

```powershell
git switch main
git pull
git switch -c feature/简短功能名称
```

完成修改并通过测试后：

```powershell
git add <修改的文件>
git commit -m "简要说明改动"
git push -u origin feature/简短功能名称
```

然后在 GitHub 创建 Pull Request，经检查后合并到 `main`。不要把下列内容提交到 Git：

- `output/` 中的 Excel 结果；
- `dist/` 中的程序、安装包和 ZIP；
- Playwright 浏览器运行时；
- Python 虚拟环境和缓存；
- 日志、任务状态、Cookie、Token 或会话数据。

## 发布与回退

每个正式版本都以不可复用的 `vX.Y.Z` Git 标签和同名 GitHub Release 作为锚点。Release 只附加已经实际构建并校验过的安装包、源码包和 SHA-256 文件；版本功能的完整历史以 [CHANGELOG.md](CHANGELOG.md) 为准。

需要撤回某次已合入的功能时，优先在新分支使用 `git revert <提交>` 创建可审计的反向提交，而不是改写已经发布的历史。需要临时检查旧版本时，可检出对应标签，例如 `git switch --detach v2.0.0`；若要重新优化旧版本，则从该标签创建新分支。`v1.0.0` 没有可验证的历史安装包，但其源码含构建脚本，仍可在合适的 Windows 环境重新生成安装包。

## 许可与责任

仓库当前未附带开源许可证。在正式对外公开、分发或允许外部人员复用前，应由项目负责人确认许可证、数据使用范围和目标网站授权。使用者需要自行确认采集行为及输出数据的合法性与合规性。

## 2.1 快速模式与复核结果

当教师目录已经同时提供姓名、学校工作邮箱、合规职称和对应的页面证据时，系统会直接收录为 `accepted`，不再访问个人主页。仅有缺邮箱、职称/专业不明确或身份冲突的记录才会访问个人页。个人页默认仅尝试 1 次，超时为 10 秒；失败后进入待复核，不拖慢整个学校任务。
正式结果 Excel 只包含 `accepted`。`review_queue.xlsx` 包含仍可重试的 `review` 和终止自动重试的 `unresolved`。`unresolved` 不代表数据错误，而是公开官方页面在当前规则下仍不足以自动确认。它不会进入正式结果，但会保留供人工处理。
每条 review 最多重处理 2 次。如果重新解析后的来源、证据与复核原因都没变，系统会提前转为 `unresolved`，以防止无意义的反复爬取。在升级邮箱解码规则、修复站点适配器、更正入口 URL 或完成访问验证后，再人工重新打开该学校的未解决项。
桌面端的“Candidate data review”会同时显示 `review`、`candidate` 和 `unresolved`。仅选中 `unresolved` 后，“Reopen unresolved”才可用；必须填写发生变化的规则、官方 URL 或访问条件，系统才会重新排队相应学校，既有 `accepted` 记录不会被覆盖。
任务结束时只生成一份 `run_report.json`。Codex 进行下一轮优化时，先读取其 `outcomes`、`diagnostics.failed_sources`、`top_review_reasons` 和 `optimization_signals`；`performance` 会按来源类型列出累计抓取耗时、重试、缓存命中、动态展开动作与停止原因，无需从普通运行日志中还原整个任务。
