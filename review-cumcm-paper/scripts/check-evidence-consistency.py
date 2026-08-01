#!/usr/bin/env python3
"""Validate a structured CUMCM paper review and compute score coverage."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


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
EVIDENCE_STATUS = {"present", "missing", "not_applicable", "unverifiable"}
MATERIAL_STATUS = {"provided", "missing", "unreadable"}
CONFIDENCE = {"high", "medium", "low"}
CLAIM_TYPE = {"fact", "judgment", "inference"}
SOURCE_KIND = {
    "problem",
    "paper_text",
    "formula",
    "figure",
    "table",
    "appendix",
    "code",
    "data",
    "prior_report",
    "global_search",
}
SEVERITY = {"fatal", "important", "general", "polish"}
RE_REVIEW_STATUS = {"resolved", "partially_resolved", "unresolved", "unverifiable"}
PROHIBITED_CLAIM_RE = re.compile(
    r"(?:获奖概率|award probability)\s*[:：=]?\s*\d"
    r"|(?:预测|预计|估计).{0,10}(?:获奖|奖项)"
    r"|(?:等同|相当于|代表).{0,10}(?:官方成绩|官方评分)"
    r"|official score\s*[:=]\s*\d",
    re.I,
)
NEGATION_NEAR_CLAIM_RE = re.compile(r"(?:不|不得|不能|并非|不是|不用于|禁止).{0,12}$")


def add_unique(items: List[str], message: str) -> None:
    if message not in items:
        items.append(message)


def get_material_status(review: Dict[str, Any], name: str) -> Optional[str]:
    aliases = {
        "original_problem": {"original_problem", "problem", "原始赛题", "赛题"},
        "paper": {"paper", "论文", "待审核论文"},
    }
    for item in review.get("materials", []):
        if item.get("name") in aliases.get(name, {name}):
            return item.get("status")
    return None


def contains_prohibited_claim(text: str) -> bool:
    for match in PROHIBITED_CLAIM_RE.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        if NEGATION_NEAR_CLAIM_RE.search(prefix):
            continue
        return True
    return False


def check_review(review: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    mode = review.get("metadata", {}).get("mode", "full")

    if contains_prohibited_claim(json.dumps(review, ensure_ascii=False)):
        errors.append("Review makes a prohibited official-score or award-probability claim.")

    for index, material in enumerate(review.get("materials", []), start=1):
        if material.get("status") not in MATERIAL_STATUS:
            errors.append(f"materials[{index}] has invalid status: {material.get('status')!r}")

    original_problem_status = get_material_status(review, "original_problem")
    paper_status = get_material_status(review, "paper")
    if mode in {"full", "re-review"} and paper_status != "provided":
        errors.append("A full or re-review requires the paper material to be provided.")

    pindex = review.get("problem_index", [])
    problem_ids = [str(item.get("id", "")).strip() for item in pindex]
    if len(problem_ids) != len(set(problem_ids)):
        errors.append("problem_index contains duplicate IDs.")
    if any(not value for value in problem_ids):
        errors.append("Every problem_index item requires a non-empty id.")
    if mode in {"full", "re-review"} and original_problem_status == "provided" and not problem_ids:
        errors.append("Original problem is provided but problem_index is empty.")
    if original_problem_status != "provided" and problem_ids:
        warnings.append(
            "problem_index is populated although original_problem is not marked provided; verify its authority."
        )

    evidence = review.get("evidence", [])
    evidence_ids = [str(item.get("id", "")).strip() for item in evidence]
    evidence_id_set: Set[str] = set(evidence_ids)
    if len(evidence_ids) != len(evidence_id_set):
        errors.append("evidence contains duplicate IDs.")
    if any(not value for value in evidence_ids):
        errors.append("Every evidence item requires a non-empty id.")

    evidence_by_id = {str(item.get("id")): item for item in evidence}
    for item in evidence:
        eid = item.get("id", "<unknown>")
        status = item.get("status")
        if status not in EVIDENCE_STATUS:
            errors.append(f"Evidence {eid} has invalid status: {status!r}")
        if item.get("claim_type") not in CLAIM_TYPE:
            errors.append(f"Evidence {eid} has invalid claim_type: {item.get('claim_type')!r}")
        if item.get("source_kind") not in SOURCE_KIND:
            errors.append(f"Evidence {eid} has invalid source_kind: {item.get('source_kind')!r}")
        if item.get("confidence") not in CONFIDENCE:
            errors.append(f"Evidence {eid} has invalid confidence: {item.get('confidence')!r}")
        location = str(item.get("location", "")).strip()
        excerpt = str(item.get("excerpt", "")).strip()
        if status == "present" and (not location or not excerpt):
            errors.append(f"Present evidence {eid} requires both location and excerpt/visual description.")
        if status == "missing":
            if item.get("source_kind") != "global_search":
                warnings.append(
                    f"Missing evidence {eid} should normally use source_kind='global_search' with a documented scope."
                )
            if not re.search(r"(全文|范围|page|页序|段落|检查)", location, re.I):
                errors.append(f"Missing evidence {eid} lacks a documented global check scope.")
        if item.get("source_kind") == "code" and re.search(
            r"(模型正确|验证通过|稳健|结果正确)", str(item.get("supports", ""))
        ):
            warnings.append(
                f"Code evidence {eid} appears to claim correctness/validation; code alone cannot prove it."
            )

    matrix = review.get("matrix", [])
    matrix_ids = [item.get("subproblem_id") for item in matrix]
    duplicate_matrix_ids = sorted(
        identifier for identifier, count in Counter(matrix_ids).items() if identifier and count > 1
    )
    if duplicate_matrix_ids:
        errors.append(
            "Matrix contains duplicate subproblem rows: " + ", ".join(duplicate_matrix_ids)
        )
    for identifier in matrix_ids:
        if identifier not in set(problem_ids):
            errors.append(f"Matrix references subproblem {identifier!r} outside the original problem index.")
    if original_problem_status == "provided":
        missing_rows = sorted(set(problem_ids) - set(matrix_ids))
        if missing_rows:
            errors.append(f"Matrix omits original subproblems: {', '.join(missing_rows)}")

    reused: Counter[str] = Counter()
    row_refs: Dict[str, List[str]] = {}
    for row in matrix:
        refs: List[str] = []
        for key in (
            "model_choice_evidence_ids",
            "result_evidence_ids",
            "validation_evidence_ids",
        ):
            values = row.get(key, []) or []
            refs.extend(values)
            for eid in values:
                if eid not in evidence_id_set:
                    errors.append(
                        f"Matrix {row.get('subproblem_id')} references unknown evidence {eid!r}."
                    )
        row_refs[str(row.get("subproblem_id"))] = refs
        reused.update(set(refs))
        if row.get("status") not in EVIDENCE_STATUS:
            errors.append(
                f"Matrix {row.get('subproblem_id')} has invalid status: {row.get('status')!r}"
            )
        if row.get("confidence") not in CONFIDENCE:
            errors.append(
                f"Matrix {row.get('subproblem_id')} has invalid confidence: {row.get('confidence')!r}"
            )
        if row.get("status") == "present" and not (row.get("paper_locations") or []):
            errors.append(
                f"Present matrix row {row.get('subproblem_id')} requires at least one paper location."
            )

    for eid, count in reused.items():
        if count <= 1:
            continue
        affected = [row for row in matrix if eid in set(row_refs.get(str(row.get("subproblem_id")), []))]
        for row in affected:
            if not str(row.get("shared_evidence_rationale", "")).strip():
                errors.append(
                    f"Evidence {eid} is reused across subproblems, but matrix {row.get('subproblem_id')} "
                    "has no shared_evidence_rationale."
                )

    dimensions = review.get("dimensions", [])
    dimension_names = [item.get("name") for item in dimensions]
    duplicate_dimensions = sorted(
        name for name, count in Counter(dimension_names).items() if name and count > 1
    )
    if duplicate_dimensions:
        errors.append("Duplicate dimensions: " + ", ".join(duplicate_dimensions))
    if mode in {"full", "re-review"}:
        names = set(dimension_names)
        missing_dimensions = set(DIMENSION_WEIGHTS) - names
        extra_dimensions = names - set(DIMENSION_WEIGHTS)
        if missing_dimensions:
            errors.append(
                "Full review omits dimensions: " + ", ".join(sorted(missing_dimensions))
            )
        if extra_dimensions:
            errors.append(
                "Full review contains unknown dimensions: " + ", ".join(sorted(extra_dimensions))
            )

    scored_weight = 0
    applicable_weight = 0
    weighted_points = 0.0
    unknown_dimensions: List[str] = []
    for item in dimensions:
        name = item.get("name")
        if name not in DIMENSION_WEIGHTS:
            continue
        expected_weight = DIMENSION_WEIGHTS[name]
        weight = item.get("weight")
        if weight != expected_weight:
            errors.append(f"Dimension {name} must use weight {expected_weight}, got {weight!r}.")
        status = item.get("status")
        score = item.get("score")
        if not str(item.get("reason", "")).strip():
            errors.append(f"Dimension {name} requires a reason.")
        if status not in EVIDENCE_STATUS:
            errors.append(f"Dimension {name} has invalid status: {status!r}")
            continue
        if item.get("confidence") not in CONFIDENCE:
            errors.append(f"Dimension {name} has invalid confidence: {item.get('confidence')!r}")
        refs = item.get("evidence_ids", []) or []
        for eid in refs:
            if eid not in evidence_id_set:
                errors.append(f"Dimension {name} references unknown evidence {eid!r}.")
        if status == "not_applicable":
            if score is not None:
                errors.append(f"Dimension {name} is not_applicable and must have score=null.")
            continue
        applicable_weight += expected_weight
        if status == "unverifiable":
            unknown_dimensions.append(name)
            if score is not None:
                errors.append(f"Dimension {name} is unverifiable and must have score=null, not zero.")
            continue
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 4:
            errors.append(f"Dimension {name} requires an integer score from 0 to 4.")
            continue
        if status == "missing" and score != 0:
            errors.append(f"Missing dimension {name} must score 0.")
        if status == "missing" and not refs:
            errors.append(
                f"Missing dimension {name} requires global-search evidence with a documented scope."
            )
        if status == "present" and not refs:
            errors.append(f"Present dimension {name} requires at least one evidence_id.")
        scored_weight += expected_weight
        weighted_points += expected_weight * score / 4.0

    task_dimension = next(
        (item for item in dimensions if item.get("name") == "任务理解与覆盖"), None
    )
    if original_problem_status != "provided" and task_dimension:
        if task_dimension.get("status") != "unverifiable" or task_dimension.get("score") is not None:
            errors.append(
                "Without a provided original problem, 任务理解与覆盖 must be unverifiable with score=null."
            )

    for issue in review.get("issues", []):
        iid = issue.get("id", "<unknown>")
        if issue.get("severity") not in SEVERITY:
            errors.append(f"Issue {iid} has invalid severity: {issue.get('severity')!r}")
        if issue.get("dimension") not in DIMENSION_WEIGHTS:
            errors.append(f"Issue {iid} has invalid dimension: {issue.get('dimension')!r}")
        for sid in issue.get("subproblem_ids", []) or []:
            if sid not in set(problem_ids):
                errors.append(f"Issue {iid} references subproblem {sid!r} outside problem_index.")
        refs = issue.get("evidence_ids", []) or []
        for eid in refs:
            if eid not in evidence_id_set:
                errors.append(f"Issue {iid} references unknown evidence {eid!r}.")
        if issue.get("severity") in {"fatal", "important"}:
            if not str(issue.get("location", "")).strip():
                errors.append(f"Fatal/important issue {iid} requires a location.")
            if not refs:
                errors.append(f"Fatal/important issue {iid} requires evidence_ids.")
            for key in ("impact", "recommendation", "completion_test", "judgment"):
                if not str(issue.get(key, "")).strip():
                    errors.append(f"Fatal/important issue {iid} requires {key}.")
        if issue.get("confidence") not in CONFIDENCE:
            errors.append(f"Issue {iid} has invalid confidence: {issue.get('confidence')!r}")

    issue_ids = {item.get("id") for item in review.get("issues", [])}
    for item in review.get("priorities", []):
        if item.get("issue_id") not in issue_ids:
            errors.append(f"Priority references unknown issue {item.get('issue_id')!r}.")
    if len(review.get("priorities", [])) > 5:
        errors.append("priorities must contain at most five items.")

    re_review_ids = []
    regression_ids = []
    for index, item in enumerate(review.get("re_review", []), start=1):
        prior_id = str(item.get("prior_issue_id", "")).strip()
        if not prior_id:
            errors.append(f"Re-review item {index} requires prior_issue_id.")
        else:
            re_review_ids.append(prior_id)
        status = item.get("status")
        if status not in RE_REVIEW_STATUS:
            errors.append(
                f"Re-review item {prior_id or index} has invalid status: {status!r}"
            )
        if not str(item.get("prior_completion_test", "")).strip():
            errors.append(f"Re-review item {prior_id or index} requires prior_completion_test.")
        if not str(item.get("note", "")).strip():
            errors.append(f"Re-review item {prior_id or index} requires note.")
        refs = item.get("current_evidence_ids", [])
        if not isinstance(refs, list):
            errors.append(
                f"Re-review item {prior_id or index} current_evidence_ids must be a list."
            )
            refs = []
        for eid in refs:
            if eid not in evidence_id_set:
                errors.append(
                    f"Re-review item {prior_id or index} references unknown evidence {eid!r}."
                )
        if status in {"resolved", "partially_resolved", "unresolved"} and not refs:
            errors.append(
                f"Re-review item {prior_id or index} status {status} requires current evidence."
            )
        if str(item.get("new_regression", "")).strip():
            errors.append(
                f"Re-review item {prior_id or index} uses deprecated new_regression text; "
                "use new_regression_issue_ids."
            )
        new_regressions = item.get("new_regression_issue_ids", [])
        if not isinstance(new_regressions, list):
            errors.append(
                f"Re-review item {prior_id or index} new_regression_issue_ids must be a list."
            )
            new_regressions = []
        for iid in new_regressions:
            regression_ids.append(iid)
            if iid not in issue_ids:
                errors.append(
                    f"Re-review item {prior_id or index} references unknown new regression {iid!r}."
                )
    duplicate_re_reviews = sorted(
        value for value, count in Counter(re_review_ids).items() if count > 1
    )
    if duplicate_re_reviews:
        errors.append("Duplicate re-review prior_issue_id values: " + ", ".join(duplicate_re_reviews))
    duplicate_regressions = sorted(
        value for value, count in Counter(regression_ids).items() if count > 1
    )
    if duplicate_regressions:
        errors.append(
            "New regression issue ids are linked more than once: "
            + ", ".join(duplicate_regressions)
        )

    reasons = {
        re.sub(r"\s+", "", str(item.get("reason", "")))
        for item in review.get("strengths", [])
        if str(item.get("reason", "")).strip()
    }
    for index, strength in enumerate(review.get("strengths", []), start=1):
        if not str(strength.get("reason", "")).strip():
            errors.append(f"Strength {index} requires a reason.")
        refs = strength.get("evidence_ids", []) or []
        if not refs:
            errors.append(f"Strength {index} requires evidence_ids.")
        for eid in refs:
            if eid not in evidence_id_set:
                errors.append(f"Strength {index} references unknown evidence {eid!r}.")
    for issue in review.get("issues", []):
        judgment = re.sub(r"\s+", "", str(issue.get("judgment", "")))
        if judgment and judgment in reasons:
            warnings.append(
                f"Issue {issue.get('id')} repeats exactly the same reason as a strength."
            )

    coverage = scored_weight / applicable_weight if applicable_weight else 0.0
    normalized_score = weighted_points / scored_weight * 100 if scored_weight else None
    score_output_allowed = bool(scored_weight and coverage >= 0.80)
    if not score_output_allowed and review.get("score_summary", {}).get("normalized_score") is not None:
        errors.append("Review outputs a total score although scored weight is below the 80% threshold.")
    if score_output_allowed and review.get("score_summary", {}).get("normalized_score") is not None:
        claimed = review["score_summary"]["normalized_score"]
        if not isinstance(claimed, (int, float)) or not math.isclose(
            float(claimed), float(normalized_score), abs_tol=0.11
        ):
            errors.append(
                f"Claimed normalized score {claimed!r} does not match computed {normalized_score:.2f}."
            )

    return {
        "schema_version": "1.0",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "computed_score": {
            "scored_weight": scored_weight,
            "applicable_weight": applicable_weight,
            "coverage": round(coverage, 4),
            "weighted_points": round(weighted_points, 4),
            "normalized_score": round(normalized_score, 2)
            if score_output_allowed and normalized_score is not None
            else None,
            "score_output_allowed": score_output_allowed,
            "unknown_dimensions": unknown_dimensions,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        review = json.loads(args.review.read_text(encoding="utf-8-sig"))
        result = check_review(review)
    except Exception as exc:
        print(f"Validation failed to run: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
