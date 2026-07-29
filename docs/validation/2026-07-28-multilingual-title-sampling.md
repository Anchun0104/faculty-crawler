# 多语言职称抽样验证记录

## 意大利语

来源页面：`https://dar.unibo.it/it/dipartimento/persone/docenti-e-ricercatori`

- 端到端解析 15 人，15 INCLUDE，0 REVIEW，0 EXCLUDE。
- `Professore ordinario` / `Professore associato` 命中原文规则，无需翻译。
- `Professoressa associata` / `Professoressa ordinaria` 通过翻译缓存后 INCLUDE，后续可补充女性形式精确规则。

## 德语

来源页面：`https://www.iak.uni-bonn.de/de/institut/abteilungen/altamerikanistik/personen`

- 端到端解析 3 人，全部 INCLUDE，0 REVIEW，0 EXCLUDE。
- `Universitätsprofessor` 命中原文规则，无需翻译。
- `Universitätsprofessorin ...` 翻译成功并 INCLUDE。
- 发现分类统计可能包含动态重复：实际记录 3 人，但 `classification_summary` 为 6。

## 法语

使用真实高校职称样本进行 pipeline 验证，并以 Unicode 转义避免 PowerShell 编码破坏：

- `Professeur des universités`：原文规则 INCLUDE，未翻译。
- `Maître de conférences`：原文规则 INCLUDE，未翻译。
- `Maîtresse de conférences`：翻译为 `Lecturer` 后 INCLUDE，但存在语义漂移风险。
- `Enseignant-chercheur`：翻译为 `Research teacher`，进入 REVIEW。
- `Chargé de recherche`：翻译为 `Research Officer`，进入 REVIEW。

## 法语规则候选

后续应优先考虑精确原文规则，不依赖机器译文：

- `Maîtresse de conférences` → `teaching_and_research` / `current`
- `Enseignant-chercheur`、`Enseignante-chercheuse` → `teaching_and_research` / `current`
- `Chargé de recherche`、`Chargée de recherche` → `research` / `current`
- `Professeure des universités` → `teaching_and_research` / `current`

本记录仅保存验证结果，不代表这些规则已加入分类器。

## 阿拉伯语

使用 Unicode 转义进行 pipeline 验证，避免 PowerShell 编码问题；5/5 均命中原文规则、无需翻译：

- `أستاذ مساعد` → INCLUDE / `teaching_and_research` / `current`
- `أستاذ مشارك` → INCLUDE / `teaching_and_research` / `current`
- `أستاذ زائر` → INCLUDE / `visiting` / `visiting`
- `باحث مشارك` → INCLUDE / `research` / `current`
- `محاضر أول` → INCLUDE / `teaching` / `current`

## 西班牙语

6/6 均 INCLUDE：

- `Profesor titular`、`Profesora titular` → 原文规则 / `teaching_and_research` / `current`
- `Profesor asociado`、`Profesora asociada` → 原文规则 / `teaching_and_research` / `current`
- `Profesor asistente` → 原文规则 / `teaching_and_research` / `current`
- `Investigador principal` → 翻译为 `Principal investigator`，归入 `research` / `current`

## 葡萄牙语

- `Professor associado`、`Professor auxiliar`、`Professor adjunto` → 原文规则 INCLUDE / `teaching_and_research` / `current`。
- `Professora associada` → 当前翻译为 `Associate teacher`，进入 REVIEW；建议补充女性形式精确规则。
- `Investigador principal` → 翻译为 `Principal investigator`，归入 `research` / `current`。
- `Professor catedrático` 的第一次测试受 PowerShell 重音字符编码影响，需用 Unicode 转义复测，不能据此确认精确规则命中。

复测确认：`Professor catedrático` 命中精确原文规则；`Professora associada` 翻译为 `Associate teacher` 后进入 REVIEW。`Professora catedrática` 本次输出不完整，暂不据此判断。

## 荷兰语

- `Hoogleraar`、`Universitair hoofddocent`、`Universitair docent`、`Docent` → 原文规则 INCLUDE / `teaching_and_research` / `current`。
- `Onderzoeker` → 翻译为 `Researcher`，因泛称歧义进入 REVIEW。

## 日语

- `教授` → `Professor`，INCLUDE / `teaching_and_research` / `current`。
- `准教授` → `Assistant Professor`，INCLUDE / `teaching_and_research` / `current`。
- `講師` → `Lecturer`，INCLUDE / `teaching_and_research` / `current`。
- `助教` → `Assistant Professor`，INCLUDE / `teaching_and_research` / `current`。
- `研究員` → `Researcher`，因泛称歧义进入 REVIEW。
