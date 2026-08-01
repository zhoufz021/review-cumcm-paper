# 独立复核与盲测协议

## 目录

- [1. 适用范围](#1-适用范围)
- [2. 隔离与冻结](#2-隔离与冻结)
- [3. Manifest](#3-manifest)
- [4. 审核输出与人工裁决](#4-审核输出与人工裁决)
- [5. 命令与状态](#5-命令与状态)

## 1. 适用范围

本协议用于两类任务：

- `independent_recheck`：第二审核者独立复核候选校准样本；
- `blind_test`：对未见优秀论文、普通/缺陷论文和真实草稿进行 4+4+4 测试。

两类任务都验证审核流程的一致性，不生成官方成绩或获奖概率。少于 12 对完整审核只能用于发现问题，不能证明评分稳定。

## 2. 隔离与冻结

管理员保留源映射、真实分层和既有结论。审核者只收到原题、论文及附件、空白模板、公开 manifest 和净化运行时，不得读取正式 `reviewed-exemplars.md`、校准索引、候选卡、旧分析、管理员映射/评估清单或另一审核者的输出。

按以下顺序执行：

1. 管理员创建公开 manifest，确认 `expected_answers_attached=false` 和 `prior_conclusion_exposure=false`；真实 4+4+4 分层另存为管理员评估 manifest。
2. 对每份论文生成净化副本并运行内容级匿名审计；文件扩展名、页数/正文哈希和必要的版式或对象计数必须保持不变。
3. 用 `build-blind-runtime.py` 复制 Skill；脚本把案例参考替换为 `BLIND_RUNTIME_STUB`。
4. intake 门禁返回 `ready` 后，审核者 A、B 分别完成并冻结 JSON。
5. 冻结后，管理员才可打开真实分层，人工回看原题和论文，裁决严重问题配对与证据位置。
6. comparison 门禁返回 `ready` 后运行一致性比较和管理员侧准确性评估。
7. 分歧导致规则修订时，换一批未见样本复测，不能在同一批样本上宣称前向验证。

## 3. Manifest

顶层必需字段：

```json
{
  "schema_version": "1.0",
  "kind": "blind_test",
  "expected_answers_attached": false,
  "anonymization_required": true,
  "sanitized_runtime_required": true,
  "runtime_skill_path": "runtime-skill-v1",
  "blindness_rules": ["..."],
  "required_groups": {
    "blind_pool": 12
  },
  "samples": []
}
```

公开样本使用预先冻结并交错分配的中性 `B01`—`B12`，`group` 一律为 `blind_pool`。优秀、普通/缺陷、真实草稿的真实分层只出现在管理员评估 manifest；冻结前不得把该文件或源映射交给审核者。管理员评估 manifest 保持同一组 `blind_id`，并把 `required_groups` 和各样本 `group` 恢复为 `excellent_unseen`、`ordinary_or_defective`、`real_draft` 各 4 份，供冻结后的 `evaluate-blind-results.py` 使用。

每个样本至少含 `blind_id`、`group`、`source_status`、论文/原题/附件路径、`prior_conclusion_exposure`、两份审核输出路径和人工裁决文件路径。`source_status` 只使用：

- `provided`：论文、原题和已声明的必要附件均已到位；
- `partial_input`：至少收到一种真实材料，但论文、原题或必要附件尚未齐全；
- `missing_input`：尚未收到该槽位的真实材料。

`partial_input` 与 `missing_input` 都不能通过 intake。不得为了让清单通过而以论文中的问题重述冒充原始赛题，也不得用人工删改的优秀论文冒充普通论文或真实草稿。

manifest 不得包含预期答案、候选分数、已验证维度分、严重问题、正反例、审核者笔记或旧一致性结论。匿名盲测的文件名、目录名和公开分组不得泄露奖项、“优秀论文”“普通论文”“草稿”等类别标签。

`anonymization_required=true` 只是审计要求，不是论文已匿名的证明。intake 必须直接检查论文二进制内容：

- DOCX：核心/自定义属性、批注、修订标记、rsid、可抽取邮箱和真实参赛队号；
- PDF：Info 字典、XMP、可抽取邮箱和真实参赛队号；
- 两种格式：文件名不得含奖项或优秀论文标签。

发现身份信息时，先用 `sanitize_blind_paper.py` 生成新副本，再用 `audit_anonymity.py` 验收。PDF 净化需安装 `pypdf`。净化失败、审计失败或净化改变正文/页面结构时，不得把 `source_status` 标为 `provided`。

## 4. 审核输出与人工裁决

两名审核者均按 [output-schema.md](output-schema.md) 输出 JSON。用于配对的 `metadata.paper_id` 或 `metadata.sample_id` 必须一致；审核者标识必须不同。

严重问题只能由人工裁决。单个 `adjudication.json` 结构为：

```json
{
  "schema_version": "1.0",
  "papers": [
    {
      "paper_id": "B02",
      "issue_matches": [
        {
          "reviewer_a_issue_id": "I01",
          "reviewer_b_issue_id": "J01",
          "verdict": "same_issue",
          "location_match": true,
          "decision": "回看原文后的裁决说明"
        }
      ],
      "unmatched_a": [],
      "unmatched_b": []
    }
  ],
  "source_audit": {
    "checked_findings": 12,
    "fabricated_locations": 0,
    "code_misclassifications": 0
  }
}
```

`verdict` 只使用 `same_issue`、`partial_overlap`、`different` 或 `unresolved`。所有致命/重要问题 ID 必须被配对或列入未配对项；存在 `unresolved` 时不得通过。

### 人工黄金准确性文件

审核结果冻结后，再由人工基于原题和原文建立 `human-gold.json`。每篇至少包含：

```json
{
  "paper_id": "B04",
  "gold_severe_issues": [
    {
      "id": "G01",
      "severity": "important",
      "dimension": "验证与稳健性",
      "location": "PDF文件页序 p.16",
      "description": "人工核验后的实质问题"
    }
  ],
  "system_issue_assessments": [
    {
      "system_issue_id": "I01",
      "gold_issue_id": "G01",
      "verdict": "true_positive",
      "location_accurate": true,
      "error_source": "none",
      "note": ""
    }
  ],
  "missed_gold_issues": []
}
```

系统问题裁决只允许 `true_positive`、`partial_overlap`、`false_positive` 或 `unresolved`。漏检项必须在 `missed_gold_issues` 中登记，并把偏差归因到 `scoring_rule`、`evidence_extraction` 或 `review_reasoning`。每个系统严重问题和人工黄金问题只能计算一次。

## 5. 命令与状态

```powershell
python scripts/sanitize_blind_paper.py --input source.pdf --output paper.pdf --report sanitize-report.json
python scripts/audit_anonymity.py --file paper.pdf --output anonymity-report.json
python scripts/check-blind-test-readiness.py --manifest manifest.json --phase intake --output intake-check.json
python scripts/check-blind-test-readiness.py --manifest manifest.json --phase comparison --output comparison-readiness.json
python scripts/compare-reviews.py --review-a reviews/reviewer-a --review-b reviews/reviewer-b --adjudication adjudication.json --output consistency-result.json
python scripts/evaluate-blind-results.py --manifest administrator-evaluation-manifest.json --system-reviews reviews/reviewer-a --gold human-gold.json --output blind-accuracy-result.json
```

`check-blind-test-readiness.py`：

- `ready`：清单合法，当前阶段所需输入或输出齐全；
- `incomplete`：结构合法但仍缺真实材料、净化运行时或审核结果；
- `invalid`：字段、分组、内容级匿名或泄漏门禁违反协议。

comparison 阶段还会解析两份审核 JSON，核对样本 ID、非空且不同的 `reviewer_id`，并确认聚合裁决文件含对应样本条目。每份审核 JSON 仍须先单独通过 `check-evidence-consistency.py`；就绪检查不替代完整审核结构校验。

`compare-reviews.py` 只有全部门禁通过才返回 `overall_status=pass`：

- 至少 12 对完整审核，计划样本全部配对；
- 原题小问索引精确一致率 100%；
- 至少 80% 的可比维度评分绝对差不超过 1；
- 对齐后的维度/逐问证据状态混淆率不超过 5%；
- 所有致命/重要问题完成人工裁决且无未决项；
- 人工原文审计覆盖每个裁决后的严重问题，虚构位置和代码误分类均为 0。

`evaluate-blind-results.py` 另要求：

- 普通/缺陷论文和真实草稿的有效严重问题召回率不低于 80%；
- 上述两组的有效严重问题精确率不低于 70%；
- 每篇含人工严重问题的普通论文或草稿至少命中一项；
- 接受匹配的严重问题位置准确率 100%；
- 人工源页审计覆盖全部系统严重问题，虚构位置和代码误分类均为 0。

人工裁定的 `partial_overlap` 在精确率和召回率中按 0.5 计。门槛在样本入场前固定，不得根据首轮结果事后降低。

加权 Cohen’s kappa、平均绝对差和严重问题对称精确匹配 F1 是描述性统计。普通论文与草稿的缺陷准确性由人工黄金评估器验收；修改前后状态识别仍需用真实成对材料另行验收。

修改前后验收至少使用两对真实材料。每对先冻结上轮审核，再完成新版审核并运行 `evaluate-revision-pairs.py`；脚本检查问题覆盖、完成标准冻结、当前证据、新回归编号和 before/after 文件差异。脚本通过只表示记录结构完整，最终状态正确性仍由未看系统结论的人工回看原文裁定。
