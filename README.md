# 高校教师信息采集工具

这是一个面向高校院系教师目录的 Python 数据采集工具。它可以从公开的教师目录页面中识别教师姓名、职称和个人主页地址，并将结果导出为 Excel。项目同时提供命令行入口和 Windows 桌面端，适合单个页面采集、批量任务、人工验证和失败诊断。

本项目采用保守、合规的访问策略：不自动破解 CAPTCHA，不绕过登录、付费墙或访问控制，不使用代理池、浏览器指纹伪装或高频请求规避封禁。使用者应遵守目标网站的服务条款、robots 规则以及适用的法律法规。

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

- 提供首页、任务列表、人工验证、会话、运行记录和设置页面。
- 可查看任务状态、失败阶段和经过脱敏的诊断信息。
- 支持单项或顺序处理人工验证任务。
- 支持管理已保存的站点会话。
- 支持生成隐私安全的问题报告 ZIP。
- 支持设置默认输出目录、任务超时和飞书共享文件夹链接。
- Windows 安装包运行时不要求目标电脑预先安装 Python。

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

发布给同事时，优先使用 GitHub Releases 中的 `FacultyCrawler-Setup-1.0.0.exe`。安装包包含桌面程序和 Playwright Chromium，正常使用不需要 Python、命令行或管理员权限。

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

项目根目录的 `VERSION` 是唯一版本来源，当前版本为 `1.0.0`。升级版本时只需修改该文件，例如从 `1.0.0` 改为 `1.1.0`；构建脚本会把版本同步写入桌面程序、安装器元数据和安装包文件名。

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
dist/FacultyCrawler/FacultyCrawler.exe
dist/installer/FacultyCrawler-Setup-1.0.0.exe
```

## 运行测试

安装运行依赖和 Chromium 后执行：

```powershell
python -m unittest discover -s tests -v
```

桌面端仍应在 Tcl/Tk 正常的 Windows 环境中完成真实窗口、Chromium、Excel 导出、安装和卸载 smoke 测试。无窗口测试不能完全替代最终 UI 验收。

## 多语言职称分类开发进度

`codex/translation` 分支已完成多语言职称分类计划的前两个阶段：

- 建立可审计的 `include`、`exclude`、`review` 三态结果模型；
- 支持 Unicode 职称规范化；
- 增加教学、研究、临床、实践、客座、兼职、博士后、Doctoral Researcher 及部分非英语学术职称规则；
- 优先排除荣休、荣誉、退休、前任、学生、助教/助研、图书馆、IT、实验技术、行政和其他专业服务岗位；
- 使用完整短语和“更长规则优先”，避免因 `assistant`、`library` 等单词误伤 `Assistant Professor` 或 `Professor of Library Science`。

当前分类器尚未接入爬虫和 Excel 导出，LibreTranslate、SQLite 缓存、三态流水线和桌面端设置也尚未实现，因此现有抓取行为保持不变。后续工作从实施计划 Task 3 开始：

- `docs/superpowers/specs/2026-07-23-multilingual-title-classification-design.md`
- `docs/superpowers/plans/2026-07-24-multilingual-title-classification.md`

## 当前缺陷与限制

### 尚未接入 AI

当前解析完全依赖确定性规则和启发式策略，尚未接入大语言模型、视觉模型或其他 AI 服务。因此：

- 遇到全新页面结构时，不能自动理解页面语义并生成解析规则。
- 无法根据页面截图智能判断哪些人物属于目标院系。
- 对模糊职称、跨语言岗位名称和不规则文本的判断能力有限。
- 解析失败后仍需要开发者查看安全诊断信息，并人工补充或调整规则。

这也意味着当前版本运行成本可控、结果可复现，并且不会把网页内容默认发送给第三方 AI 服务。

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
- GitHub 首版不保存历史 Excel 结果、浏览器运行时或安装包；这些内容应通过本地输出或 GitHub Releases 管理。
- 真实 Windows UI 和安装流程仍需在目标电脑上做最终验收。

## 后续计划

以下内容是规划方向，不代表已经实现：

1. 完善 `403` 诊断，将失败稳定区分为“可恢复”“需人工”和“不可脚本解决”。
2. 增加更多可复现的高校页面样本和解析回归测试。
3. 建立 GitHub Actions，在 Pull Request 中自动运行测试。
4. 将 Windows 安装包改为按版本标签自动构建并上传到 GitHub Releases。
5. 评估可选的 AI 辅助解析：
   - 只在规则解析失败或覆盖率过低时启用；
   - 对发送给第三方模型的数据进行最小化和脱敏；
   - 保留确定性规则作为默认路径；
   - AI 结果必须经过结构校验、置信度检查和人工复核；
   - 不使用 AI 绕过 CAPTCHA、登录或访问控制。
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

## 许可与责任

仓库当前未附带开源许可证。在正式对外公开、分发或允许外部人员复用前，应由项目负责人确认许可证、数据使用范围和目标网站授权。使用者需要自行确认采集行为及输出数据的合法性与合规性。
