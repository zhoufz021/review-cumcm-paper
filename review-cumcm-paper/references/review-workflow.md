# 审核工作流

## 目录

1. 输入门禁
2. 工作目录
3. 快速预检
4. 全面审核
5. 修改复审
6. 独立复核与盲测
7. 总分与置信度
8. 交付前门禁

## 1. 输入门禁

建立材料清单，状态只用 `provided`、`missing`、`unreadable`。

全面审核至少需要：

- 原始赛题；
- 待审核论文；
- 竞赛、年份、题号。

缺原题时仍可审查写作、图表和局部建模表达，但任务数量、覆盖、题意符合性以及依赖原题的严重问题必须标记 `unverifiable`。

缺代码或数据时不判定实现/数值错误，只审查正文是否提供了足够的算法、参数、数据处理与结果映射。公式或图表抽取失败时先渲染页面，再决定 `present` 或 `unverifiable`。

## 2. 工作目录

对单篇论文使用独立目录，避免旧报告污染：

```text
review-work/
├── inputs/
├── extraction/
│   ├── problem.json
│   └── paper.json
├── renders/
├── review.json
├── consistency.json
└── review-report.md
```

不把校准样本的人工结论放进盲测工作目录。

## 3. 快速预检

1. 检查文件是否可读、页序是否完整。
2. 从原题人工建立小问索引。
3. 检查摘要是否逐问说明任务、模型、结果和至少一项验证。
4. 检查正文是否存在问题分析、假设/变量、模型、求解、结果、验证、结论、参考文献与必要附录。
5. 检查小问是否有正文位置与结果。
6. 检查图表编号、标题、单位、图例、引用和可读性。
7. 输出 5—10 个确定性较高、可在短时间内修改的问题。

快速预检通常不输出总分；如果输出维度结果，应明确未审查范围。

## 4. 全面审核

### 4.1 抽取与视觉核验

```powershell
python scripts/extract-paper.py --input paper.pdf --output extraction/paper.json
python scripts/extract-paper.py --input problem.pdf --output extraction/problem.json
```

抽取只提供候选位置。对关键公式、表格、图像、低文字页和所有致命问题回看渲染页。DOCX 没有稳定分页时使用标题路径和段落号。

### 4.2 建立原题小问索引

每个小问至少记录：

```json
{
  "id": "Q1",
  "label": "问题1",
  "requirement": "原题任务的忠实摘要",
  "required_outputs": ["数值/方案/文件等"],
  "constraints": ["原题硬约束"],
  "source_location": "赛题文件页序或段落"
}
```

小问 ID 只来自原题。一个自然段含多个子要求时，可在 `required_outputs` 中展开，不随意新增主小问。

### 4.3 建立逐问矩阵

对每个 Q 记录：

- 输入、输出与评价标准；
- 论文分析位置；
- 变量、假设和约束；
- 模型及选择理由；
- 求解与参数；
- 结果、单位和适用条件；
- 验证链；
- 状态与置信度；
- 共享模型/结果的接口说明。

### 4.4 建立证据账本

阅读 [evidence-policy.md](evidence-policy.md)。先登记事实，再写判断，最后在必要时写推断。任何致命或重要问题必须引用证据 ID；全局缺失必须登记可靠检查范围。

### 4.5 选择专项规则

按原题核心输出选择主类型和必要副类型，阅读 [problem-type-guides.md](problem-type-guides.md)。逐项记录 `pass`、`fail`、`not_applicable` 或 `unverifiable`，不要因为使用了某个高频模型就判为通过。

### 4.6 应用十二维量表

阅读 [dimension-rubrics.md](dimension-rubrics.md)。每个维度依次完成：

1. 判断适用性；
2. 判断证据状态；
3. 与 0—4 锚点逐级比较；
4. 记录支持当前级别的证据；
5. 记录为什么没有达到下一级；
6. 给出置信度。

不得从总分或优秀论文身份反推维度分。

### 4.7 生成与校验报告

```powershell
python scripts/check-evidence-consistency.py --review review.json --output consistency.json
python scripts/build-review-report.py --review review.json --output review-report.md
```

一致性脚本出现 error 时不得交付；warning 必须人工确认并在报告中解释或修正。

## 5. 修改复审

1. 冻结上轮问题 ID、原证据和完成标准。
2. 对每条问题定位新版内容。
3. 判断根因是否解决，而不是只看措辞是否变化。
4. 记录 `resolved`、`partially_resolved`、`unresolved` 或 `unverifiable`。
5. 检查修改相邻段落、公式、图表、摘要、结论和附件是否同步。
6. 新问题在新版 `issues` 中单独编号，并把编号列入对应复审项的 `new_regression_issue_ids`。
7. 重新运行一致性检查和总分门禁。
8. 对真实 before/after 材料运行成对门禁；不得把同一文件复制两次冒充修改：

```powershell
python scripts/evaluate-revision-pairs.py --before-review before-review.json --after-review after-review.json --before-paper before.docx --after-paper after.docx --output revision-pair-result.json
```

该脚本要求上轮每个问题 ID 恰好覆盖一次、完成标准保持冻结、当前证据可解析、新回归引用新版问题 ID，并检查两份论文 SHA-256 不同。它验证复审记录的完整性，不替代人工判断“已解决/部分解决/未解决”的正确性；稳定版仍需至少两对真实修改材料的人工作为验收依据。

## 6. 独立复核与盲测

执行独立复核或 4+4+4 盲测前，阅读 [blind-test-protocol.md](blind-test-protocol.md)。管理员先建立仅含中性 B 编号和单一盲池的公开 manifest，把真实分层另存为管理员评估 manifest；公开清单不得含候选分数、证据、优缺点或旧结论。先净化并审计论文，再生成净化运行时：

```powershell
python scripts/sanitize_blind_paper.py --input source.pdf --output paper.pdf
python scripts/audit_anonymity.py --file paper.pdf
python scripts/build-blind-runtime.py --output path/to/runtime-skill-v1
python path/to/runtime-skill-v1/scripts/check-blind-test-readiness.py --manifest path/to/manifest.json --phase intake
```

只有 intake 状态为 `ready` 才开始。审核者 A、B 只访问净化运行时、匿名输入、公开 manifest 和本人输出目录；两份 JSON 冻结前不得交换结论，也不得打开源映射或管理员评估 manifest。冻结后由人工逐项裁决致命/重要问题和原文位置，再运行：

```powershell
python scripts/compare-reviews.py --review-a reviewer-a --review-b reviewer-b --adjudication adjudication.json --output consistency-result.json
python scripts/evaluate-blind-results.py --manifest administrator-evaluation-manifest.json --system-reviews reviewer-a --gold human-gold.json --output blind-accuracy-result.json
```

比较脚本给出的文本相似候选不能自动判定同一问题。人工黄金必须在审核 JSON 冻结后编制，不能提前泄漏。缺少第二审核者、人工裁决、原文位置审计或 12 对完整样本时，结果只能是诊断性 `incomplete`，不得宣称稳定评分已通过。

## 7. 总分与置信度

固定权重见维度量表。`not_applicable` 和 `unverifiable` 不进入已评分权重。

```text
coverage = scored_weight / applicable_weight
normalized_score = sum(weight * score / 4) / scored_weight * 100
```

只有 `coverage >= 0.80` 才能显示 `normalized_score`。同时显示：

- 已评分权重/适用权重；
- 未评分维度；
- 总分置信度；
- “仅用于修改排序，不是官方成绩或获奖概率”。

整体置信度参考：

- 高：原题和论文清晰，关键页面视觉核验，重要附件足以支持审查；
- 中：原题和正文可读，但代码、数据、局部公式或附件不可核验；
- 低：原题缺失、OCR 严重、重要页面不可读或证据多为间接推断。

## 8. 交付前门禁

- 原题小问数与报告一致；
- 报告没有从论文编号创造小问；
- 每条致命/重要问题有位置和证据；
- 关键词命中没有被当成完整验证；
- 代码注释没有被当成任务、结果或验证；
- 不适用与无法核验没有记零；
- 跨问复用有接口理由；
- 优点与局限没有同理由冲突；
- 图表与公式的重要判断经过视觉核验；
- 总分覆盖阈值正确；
- 报告明确非官方、非获奖概率。
