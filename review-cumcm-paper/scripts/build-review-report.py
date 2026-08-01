#!/usr/bin/env python3
"""Render a structured CUMCM review JSON as an evidence-linked Markdown report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DIMENSION_WEIGHTS = {
    "任务理解与覆盖": 10,
    "问题抽象与假设": 8,
    "数据处理质量": 8,
    "模型选择与适配": 14,
    "模型链与衔接": 8,
    "数学表达与推导": 8,
    "算法与求解": 7,
    "验证与稳健性": 12,
    "结果与可执行性": 8,
    "图表证据": 6,
    "正文写作与论证": 7,
    "可复现性与规范": 4,
}
STATUS_ZH = {
    "provided": "已提供",
    "missing": "缺失",
    "unreadable": "不可读",
    "present": "存在",
    "not_applicable": "不适用",
    "unverifiable": "无法核验",
    "resolved": "已解决",
    "partially_resolved": "部分解决",
    "unresolved": "未解决",
}
SEVERITY_ZH = {
    "fatal": "致命",
    "important": "重要",
    "general": "一般",
    "polish": "润色",
}
CONFIDENCE_ZH = {"high": "高", "medium": "中", "low": "低"}


def cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "；".join(str(item) for item in value)
    if isinstance(value, dict):
        value = "；".join(f"{key}: {val}" for key, val in value.items())
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def bullet_list(items: Iterable[Any], empty: str = "无。") -> str:
    rendered = []
    for item in items or []:
        if isinstance(item, dict):
            text = item.get("reason") or item.get("item") or item.get("description")
            if text:
                rendered.append(f"- {text}")
            else:
                rendered.append(f"- {json.dumps(item, ensure_ascii=False)}")
        else:
            rendered.append(f"- {item}")
    return "\n".join(rendered) if rendered else empty


def material_table(items: List[Dict[str, Any]]) -> str:
    lines = ["| 材料 | 状态 | 用途 | 影响 |", "| --- | --- | --- | --- |"]
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(item.get("name")),
                    cell(STATUS_ZH.get(item.get("status"), item.get("status"))),
                    cell(item.get("purpose")),
                    cell(item.get("impact")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def matrix_table(items: List[Dict[str, Any]]) -> str:
    lines = [
        "| 原题小问 | 要求 | 论文位置 | 模型 | 结果证据 | 验证证据 | 状态/置信度 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(item.get("subproblem_id")),
                    cell(item.get("requirement")),
                    cell(item.get("paper_locations")),
                    cell(item.get("models")),
                    cell(item.get("result_evidence_ids")),
                    cell(item.get("validation_evidence_ids")),
                    cell(
                        f"{STATUS_ZH.get(item.get('status'), item.get('status'))} / "
                        f"{CONFIDENCE_ZH.get(item.get('confidence'), item.get('confidence'))}"
                    ),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def compute_score(dimensions: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored_weight = 0
    applicable_weight = 0
    points = 0.0
    for item in dimensions:
        weight = DIMENSION_WEIGHTS.get(item.get("name"), item.get("weight", 0))
        status = item.get("status")
        if status == "not_applicable":
            continue
        applicable_weight += weight
        score = item.get("score")
        if status == "unverifiable" or score is None:
            continue
        scored_weight += weight
        points += weight * score / 4
    coverage = scored_weight / applicable_weight if applicable_weight else 0
    normalized = points / scored_weight * 100 if scored_weight and coverage >= 0.8 else None
    return {
        "scored_weight": scored_weight,
        "applicable_weight": applicable_weight,
        "coverage": coverage,
        "normalized": normalized,
    }


def dimensions_table(items: List[Dict[str, Any]]) -> str:
    lines = [
        "| 维度 | 权重 | 状态 | 分数 | 加权分 | 证据 | 置信度 | 判定 |",
        "| --- | ---: | --- | ---: | ---: | --- | --- | --- |",
    ]
    for item in items:
        weight = item.get("weight", DIMENSION_WEIGHTS.get(item.get("name"), ""))
        score = item.get("score")
        weighted = (
            f"{weight * score / 4:.2f}"
            if isinstance(weight, (int, float)) and isinstance(score, (int, float))
            else ""
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(item.get("name")),
                    cell(weight),
                    cell(STATUS_ZH.get(item.get("status"), item.get("status"))),
                    cell(score),
                    cell(weighted),
                    cell(item.get("evidence_ids")),
                    cell(CONFIDENCE_ZH.get(item.get("confidence"), item.get("confidence"))),
                    cell(item.get("reason")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def render_problem_type(value: Any) -> str:
    if not value:
        return "未记录。"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return bullet_list(value)
    lines = []
    for key, item in value.items():
        label = {
            "primary_type": "主类型",
            "secondary_types": "副类型",
            "passed": "已满足",
            "failed": "未满足",
            "not_applicable": "不适用",
            "unverifiable": "无法核验",
        }.get(key, key)
        lines.append(f"- {label}：{cell(item)}")
    return "\n".join(lines)


def render_issues(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "未记录问题。"
    order = {"fatal": 0, "important": 1, "general": 2, "polish": 3}
    chunks = []
    for item in sorted(items, key=lambda value: (order.get(value.get("severity"), 9), value.get("id", ""))):
        chunks.append(
            "\n".join(
                [
                    f"### {item.get('id', '')} [{SEVERITY_ZH.get(item.get('severity'), item.get('severity'))}] "
                    f"{item.get('dimension', '')}",
                    "",
                    f"- 关联小问：{cell(item.get('subproblem_ids')) or '—'}",
                    f"- 位置：{item.get('location') or '—'}",
                    f"- 证据：{cell(item.get('evidence_ids')) or '—'}",
                    f"- 原文/视觉证据：{item.get('quote') or '—'}",
                    f"- 事实：{item.get('fact') or '—'}",
                    f"- 审核判断：{item.get('judgment') or '—'}",
                    f"- 推断：{item.get('inference') or '—'}",
                    f"- 可能影响：{item.get('impact') or '—'}",
                    f"- 修改建议：{item.get('recommendation') or '—'}",
                    f"- 修改完成标准：{item.get('completion_test') or '—'}",
                    f"- 审核置信度：{CONFIDENCE_ZH.get(item.get('confidence'), item.get('confidence'))}",
                ]
            )
        )
    return "\n\n".join(chunks)


def priorities_table(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "无。"
    lines = [
        "| 优先级 | 问题 | 修改动作 | 预计收益 | 完成判据 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for item in sorted(items, key=lambda value: value.get("rank", 999))[:5]:
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(item.get("rank")),
                    cell(item.get("issue_id")),
                    cell(item.get("action")),
                    cell(item.get("benefit")),
                    cell(item.get("completion_test")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def re_review_table(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "本次不是修改复审，或未提供上轮问题。"
    lines = [
        "| 上轮问题 | 原完成标准 | 本轮证据 | 状态 | 说明 | 新回归 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(item.get("prior_issue_id")),
                    cell(item.get("prior_completion_test")),
                    cell(item.get("current_evidence_ids")),
                    cell(STATUS_ZH.get(item.get("status"), item.get("status"))),
                    cell(item.get("note")),
                    cell(item.get("new_regression")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def overall(review: Dict[str, Any]) -> str:
    if review.get("overall_conclusion"):
        return str(review["overall_conclusion"])
    strengths = review.get("strengths", [])
    issues = review.get("issues", [])
    parts = []
    if strengths:
        parts.append(f"当前可保留的主要优点是：{strengths[0].get('reason', strengths[0])}。")
    severe = [item for item in issues if item.get("severity") in {"fatal", "important"}]
    if severe:
        parts.append(
            f"最优先风险为 {severe[0].get('id')}：{severe[0].get('judgment', '见问题清单')}。"
        )
    if not parts:
        parts.append("未提供足够的结构化结论，请结合证据账本补充总体判断。")
    return "".join(parts)


def render(review: Dict[str, Any]) -> str:
    metadata = review.get("metadata", {})
    scope = review.get("scope", {})
    score = compute_score(review.get("dimensions", []))
    if score["normalized"] is None:
        normalized = (
            f"不输出（已评分权重覆盖率 {score['coverage']:.1%}，低于 80% 门槛）"
        )
    else:
        normalized = f"{score['normalized']:.1f}/100（仅用于修改排序）"

    sections = [
        "# 数学建模论文审核报告",
        "",
        "> 本报告只用于论文修改与复审，不是官方竞赛分数或获奖概率判断。",
        "",
        "## 基本信息",
        "",
        f"- 竞赛/年份/题号：{metadata.get('competition', '')} / {metadata.get('year', '')} / "
        f"{metadata.get('problem_id', '')}",
        f"- 审核模式：{metadata.get('mode', '')}",
        f"- 论文：{metadata.get('paper_path', '')}",
        f"- 原始赛题：{metadata.get('problem_path', '')}",
        f"- 审核日期：{metadata.get('review_date', '')}",
        "",
        "## 总体结论",
        "",
        overall(review),
        "",
        "## 材料完整性、范围与置信度",
        "",
        material_table(review.get("materials", [])),
        "",
        f"- 已执行：{cell(scope.get('performed')) or '—'}",
        f"- 未执行/降级：{cell(scope.get('excluded')) or '—'}",
        f"- 整体置信度：{CONFIDENCE_ZH.get(scope.get('confidence'), scope.get('confidence'))}",
        f"- 理由：{scope.get('confidence_reason', '')}",
        "",
        "## 小问—模型—结果—验证矩阵",
        "",
        matrix_table(review.get("matrix", [])),
        "",
        "## 十二维评分",
        "",
        dimensions_table(review.get("dimensions", [])),
        "",
        f"- 已评分权重/适用权重：{score['scored_weight']} / {score['applicable_weight']}",
        f"- 归一化总分：{normalized}",
        f"- 分数置信度：{CONFIDENCE_ZH.get(scope.get('confidence'), scope.get('confidence'))}",
        "",
        "## 题型专项检查",
        "",
        render_problem_type(review.get("problem_type_review")),
        "",
        "## 可保留的优点",
        "",
        bullet_list(review.get("strengths", [])),
        "",
        "## 问题清单",
        "",
        render_issues(review.get("issues", [])),
        "",
        "## 最优先修改的五项",
        "",
        priorities_table(review.get("priorities", [])),
        "",
        "## 无法核验事项",
        "",
        bullet_list(review.get("unverifiable_items", [])),
        "",
        "## 修改复审",
        "",
        re_review_table(review.get("re_review", [])),
        "",
        "## 已知限制",
        "",
        bullet_list(review.get("known_limitations", [])),
        "",
    ]
    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        review = json.loads(args.review.read_text(encoding="utf-8-sig"))
        report = render(review)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except Exception as exc:
        print(f"Report build failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
