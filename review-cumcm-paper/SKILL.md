---
name: review-cumcm-paper
description: 根据原始赛题，使用可回查原文位置的证据、十二维评分、题型专项检查和修改复审，审核 CUMCM 及类似数学建模论文。适用于 PDF、DOCX 或已抽取文本论文的快速预检；建模、验证、结果、写作和可复现性的全面审核；以及判断修改稿是否真正解决上一轮问题。
---

# 审核 CUMCM 数学建模论文

## 准备脚本环境

使用 Python 3.9 或更高版本运行脚本。处理 PDF 前，先确认当前 Python 能导入 `pdfplumber` 和 `pypdf`；缺少依赖时，从本 Skill 目录运行 `python -m pip install -r requirements.txt`。DOCX、Markdown 和纯文本处理只使用 Python 标准库。

## 明确审核约定

执行全面审核时，要求提供待审核论文、竞赛/年份/题号标识和原始赛题。将每项输入登记为 `provided`（已提供）、`missing`（缺失）或 `unreadable`（不可读）。

将论文源文件、代码、数据、赛题附件、官方格式要求、官方评阅要点和上一轮审核报告视为可选输入。缺少可选材料可能使相关结论成为 `unverifiable`（无法核验），但不能据此证明论文存在错误。

选择一种审核模式：

- `quick`：检查可读性、必要结构、摘要、赛题覆盖、图表、引用和明显缺漏。
- `full`：建立完整证据账本，执行十二维评分和题型专项检查，生成可直接用于修改的报告。
- `re-review`：逐项对照上一轮问题与修改稿，记录 `resolved`（已解决）、`partially_resolved`（部分解决）、`unresolved`（未解决）或 `unverifiable`（无法核验），并将新增回归问题单独编号。

执行全面审核或修改复审前，阅读 [review-workflow.md](references/review-workflow.md)。材料不完整时，按其中的输入降级规则执行。
执行修改复审时，在两份审核 JSON 冻结后运行 `scripts/evaluate-revision-pairs.py`；同时传入修改前后两份论文，使门禁能够拒绝用同一文件伪造成对材料。

## 抽取材料但不得虚构结构

需要复用页序或段落定位账本时，对 PDF、DOCX、Markdown 或纯文本运行 `scripts/extract-paper.py`。PDF 文本层稀疏时必须执行 OCR 或视觉核验，不得把抽取稀疏解释为内容缺失。脚本不支持旧式 DOC；应先转换格式，或将其标记为不可读。

只依据原始赛题建立权威小问索引，并保留原题标识和表述。论文中的“问题一”等标题只能用于定位讨论内容。不得根据以下内容推断额外小问：

- 模型、算法、附录、表格、图片或代码编号；
- 孤立出现的序数词或数字；
- 对同一任务的重复讨论；
- 论文章节数量。

未提供原始赛题时，将小问数量和任务覆盖结论标记为 `unverifiable`。

## 建立证据账本

为每个审核要求且只能分配一种状态：

- `present`：存在明确且可定位的证据；按证据质量评分。
- `missing`：该要求适用，并且经过可靠检查确认缺失；允许扣分。
- `not_applicable`：该要求不适用；从评分权重中排除。
- `unverifiable`：受抽取、OCR、公式、图表、数据、代码或附件限制而无法判断；不得记为 0 分。

对每条重要发现记录主张类型（`fact`、`judgment` 或 `inference`）、来源类型、位置、摘录或视觉描述以及置信度。在接受验证、模型选择、结果、图表、代码或跨小问证据前，阅读 [evidence-policy.md](references/evidence-policy.md)。

## 按证据顺序审核

1. 根据原始赛题建立“小问—输入—输出—评价标准”索引。
2. 将每个小问映射到论文的问题分析、变量、假设、模型、求解、结果和验证。
3. 判断主要题型，并阅读 [problem-type-guides.md](references/problem-type-guides.md) 中对应的专项规则。
4. 按 [dimension-rubrics.md](references/dimension-rubrics.md) 评定十二个维度。不得先给总分再倒推理由。
5. 分开记录致命正确性风险、重要可信度缺口、一般论证问题和润色问题。
6. 交付前，对结构化审核结果运行 `scripts/check-evidence-consistency.py`。
7. 使用 `scripts/build-review-report.py` 或 [review-report-template.md](assets/review-report-template.md) 生成报告。

只用 [reviewed-exemplars.md](references/reviewed-exemplars.md) 校准证据质量，不得在盲审中复制样例分数或结论。

## 保持独立复核的盲态

执行独立复核或盲测前，阅读 [blind-test-protocol.md](references/blind-test-protocol.md)。使用 `scripts/build-blind-runtime.py` 创建净化运行时，并在审核者开始工作前运行 `scripts/check-blind-test-readiness.py`。

匿名盲测时，为每篇论文分配中性公开编号，将真实样本分组保存在仅管理员可见的评估清单中。使用 `scripts/sanitize_blind_paper.py` 生成已清除元数据的副本，再要求 `scripts/audit_anonymity.py` 通过。清单中的匿名标志不能证明论文已经匿名；入场门禁必须直接审计每份 DOCX 或 PDF。

独立审核阶段只能使用原始赛题、论文及附件、空白审核模板、中性公开清单和净化运行时。不得打开正式样例文件、校准索引、候选复核卡、旧分析、管理员映射/评估清单或另一审核者的结果。两份审核 JSON 冻结后，才能人工裁决问题或运行 `scripts/compare-reviews.py`。冻结后再建立人工黄金结果并公开管理员评估清单，然后运行 `scripts/evaluate-blind-results.py` 计算实质问题的召回率、精确率和位置准确率。文本相似建议只能作为候选，不能替代人工回查原文。

## 保守评分

使用 [dimension-rubrics.md](references/dimension-rubrics.md) 中固定的维度权重和 0—4 级锚点。将 `not_applicable` 和 `unverifiable` 对应权重从已评分分母中排除。只有当已评分权重不少于适用权重的 80% 时才输出总分；否则只输出各维度结果。

为每个维度和整份报告标注置信度。证据薄弱时，即使数值分数较高，仍应保持低置信度。明确说明该分数只用于论文修改排序，不是官方竞赛分数或获奖概率。

## 生成可执行的审核报告

按照 [output-schema.md](references/output-schema.md) 输出报告，至少包括：

- 总体结论、材料完整性、审核范围和置信度；
- 小问—模型—结果—验证矩阵；
- 十二个维度的状态、允许时的分数、理由和证据；
- 题型专项检查；
- 含位置、影响、修改方法和完成性测试的分级问题清单；
- 最优先修改的五项；
- 无法核验事项和需要补充的材料；
- 修改复审检查表。

明确区分事实、判断和推断。每条致命或重要发现必须给出精确位置；若属于全局缺失，则必须明确标记，并记录已执行的检查范围。

## 禁止行为

不得：

- 仅因关键词未命中就宣称内容缺失；
- 将代码注释计为赛题小问、结果或验证；
- 将算法名称、公式、章节标题、随机模拟、收敛图或作者自评单独视为充分证据；
- 虚构页码、公式编号、数据、结果、错误或官方要求；
- 在没有明确共享接口理由时，将同一结果复用于多个小问；
- 按分数高低机械生成优点和缺点；
- 将未提供的代码、数据或不可读公式当作错误进行扣分；
- 预测获奖结果，或将本量表等同于官方评审标准。
