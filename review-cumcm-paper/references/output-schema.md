# 审核输出结构

## 目录

- [机器可读输入](#机器可读输入)
- [字段约束](#字段约束)
  - [materials](#materials)
  - [scope](#scope)
  - [problem_index](#problem_index)
  - [matrix](#matrix)
  - [evidence](#evidence)
  - [dimensions](#dimensions)
  - [issues](#issues)
  - [priorities](#priorities)
  - [re_review](#re_review)
- [人类可读报告顺序](#人类可读报告顺序)
- [独立复核与比较文件](#独立复核与比较文件)
- [提交前静态门禁](#提交前静态门禁)

## 机器可读输入

`build-review-report.py` 和 `check-evidence-consistency.py` 接受 UTF-8 JSON。顶层建议结构：

```json
{
  "metadata": {
    "competition": "CUMCM",
    "year": 2024,
    "problem_id": "A",
    "mode": "full",
    "paper_path": "paper.pdf",
    "problem_path": "problem.pdf",
    "review_date": "2026-07-31",
    "reviewer_id": "reviewer-a"
  },
  "materials": [],
  "scope": {},
  "problem_index": [],
  "matrix": [],
  "evidence": [],
  "dimensions": [],
  "problem_type_review": {},
  "strengths": [],
  "issues": [],
  "priorities": [],
  "unverifiable_items": [],
  "re_review": [],
  "known_limitations": []
}
```

## 字段约束

### materials

```json
{
  "name": "original_problem",
  "status": "provided",
  "path": "problem.pdf",
  "purpose": "建立原题小问索引",
  "impact": ""
}
```

`status` 只允许 `provided`、`missing`、`unreadable`。

### scope

```json
{
  "performed": ["..."],
  "excluded": ["..."],
  "confidence": "medium",
  "confidence_reason": "..."
}
```

### problem_index

```json
{
  "id": "Q1",
  "label": "问题1",
  "requirement": "...",
  "required_outputs": ["..."],
  "constraints": ["..."],
  "source_location": "赛题文件页序 p.2"
}
```

### matrix

```json
{
  "subproblem_id": "Q1",
  "requirement": "...",
  "paper_locations": ["PDF文件页序 p.4-8"],
  "models": ["..."],
  "model_choice_evidence_ids": ["E003"],
  "result_evidence_ids": ["E010"],
  "validation_evidence_ids": ["E011"],
  "status": "present",
  "shared_evidence_rationale": "",
  "confidence": "high"
}
```

### evidence

```json
{
  "id": "E001",
  "claim_type": "fact",
  "source_kind": "paper_text",
  "location": "PDF文件页序 p.12，表6",
  "excerpt": "...",
  "supports": "...",
  "status": "present",
  "confidence": "high"
}
```

枚举：

- `claim_type`: `fact`, `judgment`, `inference`
- `source_kind`: `problem`, `paper_text`, `formula`, `figure`, `table`, `appendix`, `code`, `data`, `prior_report`, `global_search`
- `status`: `present`, `missing`, `not_applicable`, `unverifiable`
- `confidence`: `high`, `medium`, `low`

### dimensions

```json
{
  "name": "验证与稳健性",
  "weight": 12,
  "status": "present",
  "score": 3,
  "reason": "...",
  "why_not_next_level": "...",
  "evidence_ids": ["E011", "E012"],
  "confidence": "high"
}
```

`score` 为 0—4 整数。`not_applicable` 或 `unverifiable` 时必须是 `null`。`missing` 通常为 0，但仍需说明适用性和可靠检查范围。

### issues

```json
{
  "id": "I01",
  "severity": "important",
  "dimension": "验证与稳健性",
  "subproblem_ids": ["Q2"],
  "evidence_ids": ["E020"],
  "location": "PDF文件页序 p.16，§5.2",
  "quote": "...",
  "fact": "...",
  "judgment": "...",
  "inference": "",
  "impact": "...",
  "recommendation": "...",
  "completion_test": "...",
  "confidence": "high"
}
```

`severity` 只允许 `fatal`、`important`、`general`、`polish`。

### priorities

最多 5 条：

```json
{
  "rank": 1,
  "issue_id": "I01",
  "action": "...",
  "benefit": "...",
  "completion_test": "..."
}
```

### re_review

```json
{
  "prior_issue_id": "I01",
  "prior_completion_test": "...",
  "current_evidence_ids": ["E101"],
  "status": "partially_resolved",
  "note": "...",
  "new_regression_issue_ids": ["I101"]
}
```

`status` 只允许 `resolved`、`partially_resolved`、`unresolved`、`unverifiable`。
`prior_completion_test` 必须与上轮问题原文一致；除 `unverifiable` 外，`current_evidence_ids` 至少含一项。新回归先在新版 `issues` 中独立编号，再把编号列入 `new_regression_issue_ids`，不得只写无位置的自由文本。

## 人类可读报告顺序

1. 基本信息和非官方声明；
2. 总体结论；
3. 材料完整性、范围和置信度；
4. 小问—模型—结果—验证矩阵；
5. 十二维评分与覆盖率；
6. 题型专项检查；
7. 优点；
8. 按严重度的问题清单；
9. 最优先五项；
10. 无法核验事项；
11. 复审清单/复审结果；
12. 已知限制。

报告不输出裸总分而不解释分母、置信度和非官方性质。

## 独立复核与比较文件

盲测清单、审核者输出、人工裁决和比较结果的目录、字段与冻结顺序见 [blind-test-protocol.md](blind-test-protocol.md)。两份审核 JSON 都使用本页结构，并在 `metadata.paper_id`（或 `metadata.sample_id`）写入同一个稳定标识，在 `metadata.reviewer_id` 写入不同审核者标识。

人工裁决使用单个 UTF-8 JSON，`papers` 中逐篇登记致命/重要问题的配对、未配对项和裁决，`source_audit` 汇总人工回看原文后的虚构位置数与代码误分类数。禁止把相似度候选直接写成已裁决结果。

人工黄金准确性文件必须在审核冻结后创建。每篇列出 `gold_severe_issues`、对系统严重问题的 `system_issue_assessments`、`missed_gold_issues`，并把偏差归因到 `scoring_rule`、`evidence_extraction` 或 `review_reasoning`。格式与固定门槛见 [blind-test-protocol.md](blind-test-protocol.md)。

## 提交前静态门禁

运行：

```bash
python scripts/check-evidence-consistency.py --review review.json
```

检查器至少拒绝：

- 原题索引之外或重复的小问矩阵行；
- 重复、缺失或权重错误的十二维记录；
- `present` 矩阵行没有论文位置；
- `present` 维度没有证据，或 `missing` 维度没有带检查范围的全局缺失证据；
- `not_applicable`、`unverifiable` 被记为 0；
- 跨小问复用证据却没有共享理由；
- 致命/重要意见缺位置、证据、影响、修改建议或完成标准；
- 优点引用不存在的证据；
- 低于 80% 覆盖率却输出总分；
- 把总分声称为官方成绩或给出获奖概率。
