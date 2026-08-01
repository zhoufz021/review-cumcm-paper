#!/usr/bin/env python3
"""Compare two independent CUMCM review sets and evaluate consistency gates."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


STATUSES = {"present", "missing", "not_applicable", "unverifiable"}
SEVERE = {"fatal", "important"}
DIMENSION_NAMES = [
    "任务理解与覆盖",
    "问题抽象与假设",
    "数据处理质量",
    "模型选择与适配",
    "模型链与衔接",
    "数学表达与推导",
    "算法与求解",
    "验证与稳健性",
    "结果与可执行性",
    "图表证据",
    "正文写作与论证",
    "可复现性与规范",
]


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def review_id(review: Dict[str, Any], path: Path) -> str:
    metadata = review.get("metadata", {})
    explicit = metadata.get("paper_id") or metadata.get("sample_id")
    if explicit:
        return str(explicit)
    year = metadata.get("year")
    problem = metadata.get("problem_id")
    if year and problem:
        return f"{year}{problem}"
    return path.stem


def collect_reviews(path: Path) -> Tuple[Dict[str, Tuple[Path, Dict[str, Any]]], List[str]]:
    errors: List[str] = []
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) if path.is_dir() else []
    if not files:
        return {}, [f"No review JSON files found at {path}."]
    result: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
    for file in files:
        try:
            review = load_json(file)
        except Exception as exc:
            errors.append(str(exc))
            continue
        identifier = review_id(review, file)
        if identifier in result:
            errors.append(
                f"Duplicate review identity {identifier!r}: {result[identifier][0]} and {file}."
            )
            continue
        result[identifier] = (file, review)
    return result, errors


def quadratic_weighted_kappa(values_a: Sequence[int], values_b: Sequence[int]) -> Optional[float]:
    if not values_a or len(values_a) != len(values_b):
        return None
    size = 5
    total = len(values_a)
    observed = [[0 for _ in range(size)] for _ in range(size)]
    hist_a = [0 for _ in range(size)]
    hist_b = [0 for _ in range(size)]
    for a, b in zip(values_a, values_b):
        observed[a][b] += 1
        hist_a[a] += 1
        hist_b[b] += 1
    observed_disagreement = 0.0
    expected_disagreement = 0.0
    denominator = float((size - 1) ** 2)
    for i in range(size):
        for j in range(size):
            weight = ((i - j) ** 2) / denominator
            observed_disagreement += weight * observed[i][j] / total
            expected_disagreement += weight * hist_a[i] * hist_b[j] / (total * total)
    if math.isclose(expected_disagreement, 0.0):
        return 1.0 if math.isclose(observed_disagreement, 0.0) else None
    return 1.0 - observed_disagreement / expected_disagreement


def char_bigrams(value: str) -> set:
    normalized = re.sub(r"\s+", "", value or "")
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def jaccard(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def severe_issues(review: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for item in review.get("issues", []):
        if item.get("severity") in SEVERE and item.get("id"):
            result[str(item["id"])] = item
    return result


def issue_similarity(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    score = 0.0
    if left.get("dimension") == right.get("dimension"):
        score += 0.35
    if left.get("severity") == right.get("severity"):
        score += 0.15
    left_q = set(left.get("subproblem_ids", []) or [])
    right_q = set(right.get("subproblem_ids", []) or [])
    score += 0.20 * jaccard(left_q, right_q)
    left_text = " ".join(
        str(left.get(key, "")) for key in ("judgment", "fact", "impact")
    )
    right_text = " ".join(
        str(right.get(key, "")) for key in ("judgment", "fact", "impact")
    )
    score += 0.30 * jaccard(char_bigrams(left_text), char_bigrams(right_text))
    return round(score, 4)


def candidate_issue_matches(
    issues_a: Dict[str, Dict[str, Any]], issues_b: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    candidates = []
    for aid, left in issues_a.items():
        ranked = sorted(
            (
                (issue_similarity(left, right), bid)
                for bid, right in issues_b.items()
            ),
            reverse=True,
        )
        if ranked:
            score, bid = ranked[0]
            candidates.append(
                {
                    "reviewer_a_issue_id": aid,
                    "reviewer_b_candidate_id": bid,
                    "similarity": score,
                    "interpretation": "candidate_only_requires_human_adjudication",
                }
            )
    return candidates


def status_pair(
    left: str, right: str, confusion: Dict[str, Counter], warnings: List[str], label: str
) -> bool:
    if left not in STATUSES or right not in STATUSES:
        warnings.append(f"{label} contains an invalid or missing evidence status.")
        return False
    confusion[left][right] += 1
    return left == right


def compare_pair(
    identifier: str, review_a: Dict[str, Any], review_b: Dict[str, Any]
) -> Dict[str, Any]:
    warnings: List[str] = []
    pids_a = [str(item.get("id", "")) for item in review_a.get("problem_index", [])]
    pids_b = [str(item.get("id", "")) for item in review_b.get("problem_index", [])]
    problem_exact = pids_a == pids_b

    dims_a = {item.get("name"): item for item in review_a.get("dimensions", [])}
    dims_b = {item.get("name"): item for item in review_b.get("dimensions", [])}
    dimension_rows = []
    confusion: Dict[str, Counter] = defaultdict(Counter)
    for name in DIMENSION_NAMES:
        left = dims_a.get(name)
        right = dims_b.get(name)
        if not left or not right:
            warnings.append(f"{identifier}: dimension {name} is missing from one reviewer.")
            continue
        status_equal = status_pair(
            left.get("status"),
            right.get("status"),
            confusion,
            warnings,
            f"{identifier}/{name}",
        )
        score_a = left.get("score")
        score_b = right.get("score")
        comparable = (
            isinstance(score_a, int)
            and not isinstance(score_a, bool)
            and isinstance(score_b, int)
            and not isinstance(score_b, bool)
            and 0 <= score_a <= 4
            and 0 <= score_b <= 4
        )
        difference = abs(score_a - score_b) if comparable else None
        dimension_rows.append(
            {
                "name": name,
                "status_a": left.get("status"),
                "status_b": right.get("status"),
                "status_equal": status_equal,
                "score_a": score_a,
                "score_b": score_b,
                "absolute_difference": difference,
                "within_one": difference is not None and difference <= 1,
            }
        )

    matrix_a = {
        str(item.get("subproblem_id")): item for item in review_a.get("matrix", [])
    }
    matrix_b = {
        str(item.get("subproblem_id")): item for item in review_b.get("matrix", [])
    }
    matrix_rows = []
    for qid in sorted(set(matrix_a) | set(matrix_b)):
        left = matrix_a.get(qid)
        right = matrix_b.get(qid)
        if not left or not right:
            warnings.append(f"{identifier}: matrix row {qid} is missing from one reviewer.")
            continue
        equal = status_pair(
            left.get("status"),
            right.get("status"),
            confusion,
            warnings,
            f"{identifier}/matrix/{qid}",
        )
        matrix_rows.append(
            {
                "subproblem_id": qid,
                "status_a": left.get("status"),
                "status_b": right.get("status"),
                "status_equal": equal,
            }
        )

    issues_a = severe_issues(review_a)
    issues_b = severe_issues(review_b)
    return {
        "paper_id": identifier,
        "problem_index": {
            "ids_a": pids_a,
            "ids_b": pids_b,
            "exact_ordered_match": problem_exact,
        },
        "dimensions": dimension_rows,
        "matrix_statuses": matrix_rows,
        "status_confusion": {
            left: dict(row) for left, row in sorted(confusion.items())
        },
        "severe_issues": {
            "reviewer_a": sorted(issues_a),
            "reviewer_b": sorted(issues_b),
            "candidate_matches": candidate_issue_matches(issues_a, issues_b),
            "metrics_status": "requires_human_adjudication",
        },
        "warnings": warnings,
    }


def adjudication_metrics(
    adjudication: Optional[Dict[str, Any]],
    pairs: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    counts_a = sum(len(severe_issues(left)) for left, _ in pairs.values())
    counts_b = sum(len(severe_issues(right)) for _, right in pairs.values())
    result: Dict[str, Any] = {
        "reviewer_a_severe_count": counts_a,
        "reviewer_b_severe_count": counts_b,
        "same_issue_matches": 0,
        "partial_overlap_matches": 0,
        "different_matches": 0,
        "unresolved_matches": 0,
        "unmatched_a_count": 0,
        "unmatched_b_count": 0,
        "all_issue_ids_accounted_for": False,
        "adjudication_complete": False,
        "symmetric_exact_match_f1": None,
        "errors": [],
    }
    if adjudication is None:
        result["status"] = "not_provided"
        return result

    paper_entries = adjudication.get("papers", [])
    if not isinstance(paper_entries, list):
        result["errors"].append("adjudication.papers must be a list.")
        paper_entries = []
    by_paper = {}
    for item in paper_entries:
        if not isinstance(item, dict):
            result["errors"].append("Every adjudication.papers entry must be an object.")
            continue
        paper_id = str(item.get("paper_id", ""))
        if not paper_id:
            result["errors"].append("Every adjudication.papers entry requires paper_id.")
        elif paper_id in by_paper:
            result["errors"].append(f"{paper_id}: duplicate adjudication entry.")
        else:
            by_paper[paper_id] = item
    for paper_id in sorted(set(by_paper) - set(pairs)):
        result["errors"].append(f"{paper_id}: adjudication entry has no paired reviews.")
    accounted_a = set()
    accounted_b = set()
    for paper_id, (review_a, review_b) in pairs.items():
        entry = by_paper.get(paper_id)
        issues_a = severe_issues(review_a)
        issues_b = severe_issues(review_b)
        if entry is None:
            result["errors"].append(f"{paper_id}: adjudication entry is missing.")
            continue
        seen_a = set()
        seen_b = set()
        for match in entry.get("issue_matches", []):
            aid = str(match.get("reviewer_a_issue_id", ""))
            bid = str(match.get("reviewer_b_issue_id", ""))
            verdict = match.get("verdict")
            if aid not in issues_a:
                result["errors"].append(f"{paper_id}: unknown reviewer A issue {aid!r}.")
                continue
            if bid not in issues_b:
                result["errors"].append(f"{paper_id}: unknown reviewer B issue {bid!r}.")
                continue
            if aid in seen_a:
                result["errors"].append(
                    f"{paper_id}: reviewer A issue {aid!r} is adjudicated more than once."
                )
                continue
            if bid in seen_b:
                result["errors"].append(
                    f"{paper_id}: reviewer B issue {bid!r} is adjudicated more than once."
                )
                continue
            seen_a.add(aid)
            seen_b.add(bid)
            accounted_a.add((paper_id, aid))
            accounted_b.add((paper_id, bid))
            if verdict == "same_issue":
                result["same_issue_matches"] += 1
            elif verdict == "partial_overlap":
                result["partial_overlap_matches"] += 1
            elif verdict == "different":
                result["different_matches"] += 1
            elif verdict == "unresolved":
                result["unresolved_matches"] += 1
            else:
                result["errors"].append(f"{paper_id}: invalid verdict {verdict!r}.")
        for aid in entry.get("unmatched_a", []):
            if aid not in issues_a:
                result["errors"].append(f"{paper_id}: unknown unmatched A issue {aid!r}.")
            elif aid in seen_a:
                result["errors"].append(
                    f"{paper_id}: reviewer A issue {aid!r} is adjudicated more than once."
                )
            else:
                seen_a.add(aid)
                accounted_a.add((paper_id, aid))
                result["unmatched_a_count"] += 1
        for bid in entry.get("unmatched_b", []):
            if bid not in issues_b:
                result["errors"].append(f"{paper_id}: unknown unmatched B issue {bid!r}.")
            elif bid in seen_b:
                result["errors"].append(
                    f"{paper_id}: reviewer B issue {bid!r} is adjudicated more than once."
                )
            else:
                seen_b.add(bid)
                accounted_b.add((paper_id, bid))
                result["unmatched_b_count"] += 1

    all_a = {
        (paper_id, issue_id)
        for paper_id, (review, _) in pairs.items()
        for issue_id in severe_issues(review)
    }
    all_b = {
        (paper_id, issue_id)
        for paper_id, (_, review) in pairs.items()
        for issue_id in severe_issues(review)
    }
    result["all_issue_ids_accounted_for"] = accounted_a == all_a and accounted_b == all_b
    result["adjudication_complete"] = (
        not result["errors"]
        and result["all_issue_ids_accounted_for"]
        and result["unresolved_matches"] == 0
    )
    denominator = counts_a + counts_b
    if denominator:
        result["symmetric_exact_match_f1"] = round(
            2 * result["same_issue_matches"] / denominator, 4
        )
    elif result["adjudication_complete"]:
        result["symmetric_exact_match_f1"] = 1.0
    result["status"] = "complete" if result["adjudication_complete"] else "incomplete"
    return result


def source_audit_metrics(adjudication: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    audit = adjudication.get("source_audit") if adjudication else None
    if not isinstance(audit, dict):
        return {
            "status": "not_provided",
            "checked_findings": 0,
            "fabricated_locations": None,
            "code_misclassifications": None,
        }
    checked = audit.get("checked_findings")
    fabricated = audit.get("fabricated_locations")
    code = audit.get("code_misclassifications")
    valid = all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (checked, fabricated, code)
    )
    return {
        "status": "complete" if valid and checked > 0 else "incomplete",
        "checked_findings": checked,
        "fabricated_locations": fabricated,
        "code_misclassifications": code,
    }


def gate(name: str, status: str, value: Any, threshold: str, reason: str) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "value": value,
        "threshold": threshold,
        "reason": reason,
    }


def compare_sets(
    set_a: Dict[str, Tuple[Path, Dict[str, Any]]],
    set_b: Dict[str, Tuple[Path, Dict[str, Any]]],
    adjudication: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    ids_a = set(set_a)
    ids_b = set(set_b)
    common = sorted(ids_a & ids_b)
    missing_a = sorted(ids_b - ids_a)
    missing_b = sorted(ids_a - ids_b)
    pair_objects = {
        identifier: (set_a[identifier][1], set_b[identifier][1]) for identifier in common
    }
    pair_reports = [
        compare_pair(identifier, left, right)
        for identifier, (left, right) in pair_objects.items()
    ]

    all_dim_rows = [row for pair in pair_reports for row in pair["dimensions"]]
    comparable = [
        row for row in all_dim_rows if row["absolute_difference"] is not None
    ]
    scores_a = [row["score_a"] for row in comparable]
    scores_b = [row["score_b"] for row in comparable]
    differences = [row["absolute_difference"] for row in comparable]
    by_dimension: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in comparable:
        by_dimension[row["name"]].append(row)
    dimension_summary = {}
    for name in DIMENSION_NAMES:
        rows = by_dimension.get(name, [])
        dimension_summary[name] = {
            "comparable_pairs": len(rows),
            "exact_rate": round(sum(row["absolute_difference"] == 0 for row in rows) / len(rows), 4)
            if rows
            else None,
            "within_one_rate": round(sum(row["within_one"] for row in rows) / len(rows), 4)
            if rows
            else None,
            "mean_absolute_difference": round(
                sum(row["absolute_difference"] for row in rows) / len(rows), 4
            )
            if rows
            else None,
            "quadratic_weighted_kappa": round(
                quadratic_weighted_kappa(
                    [row["score_a"] for row in rows],
                    [row["score_b"] for row in rows],
                ),
                4,
            )
            if rows and quadratic_weighted_kappa(
                [row["score_a"] for row in rows],
                [row["score_b"] for row in rows],
            )
            is not None
            else None,
        }

    status_rows = []
    confusion: Dict[str, Counter] = defaultdict(Counter)
    for pair in pair_reports:
        for row in pair["dimensions"] + pair["matrix_statuses"]:
            left = row.get("status_a")
            right = row.get("status_b")
            if left in STATUSES and right in STATUSES:
                status_rows.append((left, right))
                confusion[left][right] += 1

    subproblem_rate = (
        sum(pair["problem_index"]["exact_ordered_match"] for pair in pair_reports)
        / len(pair_reports)
        if pair_reports
        else None
    )
    within_one_rate = (
        sum(row["within_one"] for row in comparable) / len(comparable) if comparable else None
    )
    status_agreement = (
        sum(left == right for left, right in status_rows) / len(status_rows)
        if status_rows
        else None
    )
    issue_metrics = adjudication_metrics(adjudication, pair_objects)
    source_metrics = source_audit_metrics(adjudication)
    minimum_source_checks = (
        issue_metrics["same_issue_matches"]
        + issue_metrics["partial_overlap_matches"]
        + 2 * issue_metrics["different_matches"]
        + issue_metrics["unmatched_a_count"]
        + issue_metrics["unmatched_b_count"]
    )

    gates = []
    gates.append(
        gate(
            "minimum_corpus_size",
            "pass" if len(common) >= 12 else "incomplete",
            len(common),
            ">= 12 paired papers",
            "A smaller set is diagnostic only and cannot prove stable scoring.",
        )
    )
    gates.append(
        gate(
            "paired_review_coverage",
            "pass" if not missing_a and not missing_b and common else "incomplete",
            {"missing_a": missing_a, "missing_b": missing_b},
            "all planned papers have both reviews",
            "Unpaired papers cannot enter consistency metrics.",
        )
    )
    gates.append(
        gate(
            "subproblem_index_exact",
            "pass" if subproblem_rate == 1.0 else "fail" if subproblem_rate is not None else "incomplete",
            round(subproblem_rate, 4) if subproblem_rate is not None else None,
            "100%",
            "Both reviewers must use the original problem index exactly.",
        )
    )
    gates.append(
        gate(
            "dimension_within_one",
            "pass"
            if within_one_rate is not None and within_one_rate >= 0.80
            else "fail"
            if within_one_rate is not None
            else "incomplete",
            round(within_one_rate, 4) if within_one_rate is not None else None,
            ">= 80% of comparable dimension scores differ by at most 1",
            "This operationalizes 'most dimensions' before testing begins.",
        )
    )
    confusion_rate = 1.0 - status_agreement if status_agreement is not None else None
    gates.append(
        gate(
            "evidence_status_confusion",
            "pass"
            if confusion_rate is not None and confusion_rate <= 0.05
            else "fail"
            if confusion_rate is not None
            else "incomplete",
            round(confusion_rate, 4) if confusion_rate is not None else None,
            "<= 5% across aligned dimension and subproblem statuses",
            "Evidence-ledger items require separate adjudication because their IDs are reviewer-specific.",
        )
    )
    gates.append(
        gate(
            "severe_issue_adjudication",
            "pass"
            if issue_metrics["adjudication_complete"]
            else "fail"
            if adjudication is not None
            else "incomplete",
            issue_metrics["status"],
            "all fatal/important issue IDs accounted for; no unresolved matches",
            "Text similarity only proposes candidates and never decides issue equivalence.",
        )
    )
    source_pass = (
        source_metrics["status"] == "complete"
        and source_metrics["checked_findings"] >= minimum_source_checks
        and source_metrics["fabricated_locations"] == 0
        and source_metrics["code_misclassifications"] == 0
    )
    gates.append(
        gate(
            "source_audit",
            "pass"
            if source_pass
            else "fail"
            if source_metrics["status"] == "complete"
            else "incomplete",
            {**source_metrics, "minimum_checked_findings": minimum_source_checks},
            "manual source audit covers every adjudicated severe finding; 0 fabricated locations and 0 code misclassifications",
            "This cannot be inferred from two review JSON files alone.",
        )
    )

    statuses = {item["status"] for item in gates}
    overall = "fail" if "fail" in statuses else "incomplete" if "incomplete" in statuses else "pass"
    return {
        "schema_version": "1.0",
        "pair_count": len(common),
        "paired_ids": common,
        "unpaired": {"missing_from_a": missing_a, "missing_from_b": missing_b},
        "aggregate": {
            "subproblem_exact_rate": round(subproblem_rate, 4)
            if subproblem_rate is not None
            else None,
            "dimensions": {
                "comparable_pairs": len(comparable),
                "exact_rate": round(sum(value == 0 for value in differences) / len(differences), 4)
                if differences
                else None,
                "within_one_rate": round(within_one_rate, 4)
                if within_one_rate is not None
                else None,
                "mean_absolute_difference": round(sum(differences) / len(differences), 4)
                if differences
                else None,
                "quadratic_weighted_kappa_pooled": round(
                    quadratic_weighted_kappa(scores_a, scores_b), 4
                )
                if quadratic_weighted_kappa(scores_a, scores_b) is not None
                else None,
                "by_dimension": dimension_summary,
            },
            "statuses": {
                "scope": "aligned dimension and subproblem statuses",
                "aligned_items": len(status_rows),
                "agreement_rate": round(status_agreement, 4)
                if status_agreement is not None
                else None,
                "confusion_rate": round(confusion_rate, 4)
                if confusion_rate is not None
                else None,
                "confusion_matrix": {
                    left: dict(row) for left, row in sorted(confusion.items())
                },
            },
            "severe_issues": issue_metrics,
            "source_audit": source_metrics,
        },
        "gates": gates,
        "overall_status": overall,
        "pairs": pair_reports,
        "interpretation_limits": [
            "Quadratic weighted kappa is descriptive; report per-dimension values over the full corpus.",
            "Issue similarity proposes adjudication candidates and never establishes agreement.",
            "Evidence fabrication and code misclassification require manual source-page audit.",
            "A corpus smaller than 12 paired papers cannot prove stable scoring.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-a", required=True, type=Path, help="Reviewer A JSON file or directory.")
    parser.add_argument("--review-b", required=True, type=Path, help="Reviewer B JSON file or directory.")
    parser.add_argument("--adjudication", type=Path, help="Optional human adjudication JSON.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    set_a, errors_a = collect_reviews(args.review_a)
    set_b, errors_b = collect_reviews(args.review_b)
    if errors_a or errors_b:
        for message in errors_a + errors_b:
            print(message, file=sys.stderr)
        return 2
    try:
        adjudication = load_json(args.adjudication) if args.adjudication else None
        result = compare_sets(set_a, set_b, adjudication)
    except Exception as exc:
        print(f"Comparison failed to run: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0 if result["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
