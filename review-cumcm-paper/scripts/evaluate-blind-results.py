#!/usr/bin/env python3
"""Evaluate blind-review accuracy against post-freeze human gold issues."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SEVERE = {"fatal", "important"}
VERDICTS = {"true_positive", "partial_overlap", "false_positive", "unresolved"}
ERROR_SOURCES = {
    "none",
    "scoring_rule",
    "evidence_extraction",
    "review_reasoning",
}
SUBSTANTIVE_GROUPS = {"ordinary_or_defective", "real_draft"}
EVALUATION_GROUPS = {"excellent_unseen", *SUBSTANTIVE_GROUPS}


def load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value


def review_id(review: Dict[str, Any], path: Path) -> str:
    metadata = review.get("metadata", {})
    return str(
        metadata.get("paper_id")
        or metadata.get("sample_id")
        or path.stem
    )


def collect_reviews(path: Path) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) if path.is_dir() else []
    if not files:
        return {}, [f"No system-review JSON files found at {path}."]
    reviews: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for file in files:
        try:
            review = load_object(file)
        except Exception as exc:
            errors.append(str(exc))
            continue
        identifier = review_id(review, file)
        if identifier in reviews:
            errors.append(f"Duplicate system-review identity {identifier!r}.")
        else:
            reviews[identifier] = review
    return reviews, errors


def severe_issues(review: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in review.get("issues", [])
        if item.get("severity") in SEVERE and item.get("id")
    }


def rate(numerator: float, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def gate(name: str, status: str, value: Any, threshold: str, reason: str) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "value": value,
        "threshold": threshold,
        "reason": reason,
    }


def evaluate(
    manifest: Dict[str, Any],
    reviews: Dict[str, Dict[str, Any]],
    gold: Dict[str, Any],
) -> Dict[str, Any]:
    errors: List[str] = []
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise ValueError("manifest.samples must be a list.")
    sample_by_id: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            errors.append("Every manifest sample must be an object.")
            continue
        sample_id = str(sample.get("blind_id", "")).strip()
        if not sample_id:
            errors.append("Every manifest sample requires blind_id.")
        elif sample_id in sample_by_id:
            errors.append(f"Duplicate manifest blind_id {sample_id!r}.")
        else:
            sample_by_id[sample_id] = sample

    required_groups = manifest.get("required_groups", {})
    actual_groups = Counter(
        str(sample.get("group", "")) for sample in sample_by_id.values()
    )
    missing_evaluation_groups = sorted(EVALUATION_GROUPS - set(actual_groups))
    if missing_evaluation_groups:
        errors.append(
            "Accuracy evaluation requires the post-freeze administrator manifest "
            "with true 4+4+4 groups; missing: "
            + ", ".join(missing_evaluation_groups)
        )
    for group, required in required_groups.items():
        if actual_groups.get(group, 0) != required:
            errors.append(
                f"Group {group!r} requires {required} samples, found {actual_groups.get(group, 0)}."
            )

    gold_entries = gold.get("papers")
    if not isinstance(gold_entries, list):
        raise ValueError("gold.papers must be a list.")
    gold_by_id: Dict[str, Dict[str, Any]] = {}
    for entry in gold_entries:
        if not isinstance(entry, dict):
            errors.append("Every gold.papers entry must be an object.")
            continue
        paper_id = str(entry.get("paper_id", "")).strip()
        if not paper_id:
            errors.append("Every gold.papers entry requires paper_id.")
        elif paper_id in gold_by_id:
            errors.append(f"Duplicate gold paper_id {paper_id!r}.")
        else:
            gold_by_id[paper_id] = entry

    expected_ids = set(sample_by_id)
    provided_ids = {
        paper_id
        for paper_id, sample in sample_by_id.items()
        if sample.get("source_status") == "provided"
    }
    missing_input_ids = sorted(expected_ids - provided_ids)
    missing_review_ids = sorted(expected_ids - set(reviews))
    extra_review_ids = sorted(set(reviews) - expected_ids)
    missing_gold_ids = sorted(expected_ids - set(gold_by_id))
    extra_gold_ids = sorted(set(gold_by_id) - expected_ids)
    if extra_review_ids:
        errors.append("System reviews contain undeclared samples: " + ", ".join(extra_review_ids))
    if extra_gold_ids:
        errors.append("Human gold contains undeclared samples: " + ", ".join(extra_gold_ids))

    paper_results = []
    aggregate = Counter()
    location_checked = 0
    location_correct = 0
    attribution = Counter()
    papers_with_gold_defects = 0
    papers_with_detected_defects = 0
    substantive_paper_ids = {
        paper_id
        for paper_id, sample in sample_by_id.items()
        if sample.get("group") in SUBSTANTIVE_GROUPS
    }

    for paper_id in sorted(expected_ids & set(reviews) & set(gold_by_id)):
        sample = sample_by_id[paper_id]
        review_issues = severe_issues(reviews[paper_id])
        entry = gold_by_id[paper_id]
        gold_issues_raw = entry.get("gold_severe_issues")
        if not isinstance(gold_issues_raw, list):
            errors.append(f"{paper_id}: gold_severe_issues must be a list.")
            gold_issues_raw = []
        gold_issues: Dict[str, Dict[str, Any]] = {}
        for item in gold_issues_raw:
            if not isinstance(item, dict):
                errors.append(f"{paper_id}: every gold issue must be an object.")
                continue
            issue_id = str(item.get("id", "")).strip()
            if not issue_id or issue_id in gold_issues:
                errors.append(f"{paper_id}: gold issue IDs must be non-empty and unique.")
                continue
            if item.get("severity") not in SEVERE:
                errors.append(f"{paper_id}/{issue_id}: severity must be fatal or important.")
            if not str(item.get("location", "")).strip():
                errors.append(f"{paper_id}/{issue_id}: gold issue requires a source location.")
            if not str(item.get("description", "")).strip():
                errors.append(f"{paper_id}/{issue_id}: gold issue requires a description.")
            gold_issues[issue_id] = item

        assessments = entry.get("system_issue_assessments")
        if not isinstance(assessments, list):
            errors.append(f"{paper_id}: system_issue_assessments must be a list.")
            assessments = []
        seen_system = set()
        seen_gold = set()
        counts = Counter()
        accepted_gold = set()
        for assessment in assessments:
            if not isinstance(assessment, dict):
                errors.append(f"{paper_id}: every assessment must be an object.")
                continue
            system_id = str(assessment.get("system_issue_id", "")).strip()
            gold_id = str(assessment.get("gold_issue_id") or "").strip()
            verdict = assessment.get("verdict")
            error_source = assessment.get("error_source")
            if system_id not in review_issues:
                errors.append(f"{paper_id}: unknown system issue {system_id!r}.")
                continue
            if system_id in seen_system:
                errors.append(f"{paper_id}: system issue {system_id!r} is assessed more than once.")
                continue
            seen_system.add(system_id)
            if verdict not in VERDICTS:
                errors.append(f"{paper_id}/{system_id}: invalid verdict {verdict!r}.")
                continue
            if error_source not in ERROR_SOURCES:
                errors.append(
                    f"{paper_id}/{system_id}: invalid error_source {error_source!r}."
                )
            attribution[str(error_source)] += 1
            if verdict == "false_positive":
                if gold_id:
                    errors.append(
                        f"{paper_id}/{system_id}: false_positive must not reference a gold issue."
                    )
                counts["false_positive"] += 1
                continue
            if gold_id not in gold_issues:
                errors.append(f"{paper_id}/{system_id}: unknown gold issue {gold_id!r}.")
                continue
            if gold_id in seen_gold:
                errors.append(f"{paper_id}: gold issue {gold_id!r} is matched more than once.")
                continue
            seen_gold.add(gold_id)
            if verdict == "true_positive":
                counts["true_positive"] += 1
                accepted_gold.add(gold_id)
            elif verdict == "partial_overlap":
                counts["partial_overlap"] += 1
                accepted_gold.add(gold_id)
            else:
                counts["unresolved"] += 1
            if verdict in {"true_positive", "partial_overlap"}:
                accurate = assessment.get("location_accurate")
                if not isinstance(accurate, bool):
                    errors.append(
                        f"{paper_id}/{system_id}: accepted match requires boolean location_accurate."
                    )
                else:
                    location_checked += 1
                    location_correct += int(accurate)

        missed = entry.get("missed_gold_issues")
        if not isinstance(missed, list):
            errors.append(f"{paper_id}: missed_gold_issues must be a list.")
            missed = []
        missed_ids = set()
        for item in missed:
            if not isinstance(item, dict):
                errors.append(f"{paper_id}: every missed-gold entry must be an object.")
                continue
            gold_id = str(item.get("gold_issue_id", "")).strip()
            error_source = item.get("error_source")
            if gold_id not in gold_issues:
                errors.append(f"{paper_id}: unknown missed gold issue {gold_id!r}.")
                continue
            if gold_id in seen_gold or gold_id in missed_ids:
                errors.append(f"{paper_id}: gold issue {gold_id!r} is accounted more than once.")
                continue
            if error_source not in ERROR_SOURCES - {"none"}:
                errors.append(
                    f"{paper_id}/{gold_id}: missed issue needs a non-none error_source."
                )
            attribution[str(error_source)] += 1
            missed_ids.add(gold_id)
            counts["missed"] += 1

        unaccounted_system = sorted(set(review_issues) - seen_system)
        unaccounted_gold = sorted(set(gold_issues) - seen_gold - missed_ids)
        if unaccounted_system:
            errors.append(
                f"{paper_id}: unaccounted system issues: {', '.join(unaccounted_system)}."
            )
        if unaccounted_gold:
            errors.append(
                f"{paper_id}: unaccounted gold issues: {', '.join(unaccounted_gold)}."
            )

        effective_tp = counts["true_positive"] + 0.5 * counts["partial_overlap"]
        aggregate.update(counts)
        aggregate["system_issue_count"] += len(review_issues)
        aggregate["gold_issue_count"] += len(gold_issues)
        if sample.get("group") in SUBSTANTIVE_GROUPS:
            aggregate["substantive_system_issue_count"] += len(review_issues)
            aggregate["substantive_gold_issue_count"] += len(gold_issues)
            aggregate["substantive_true_positive"] += counts["true_positive"]
            aggregate["substantive_partial_overlap"] += counts["partial_overlap"]
            if gold_issues:
                papers_with_gold_defects += 1
                if accepted_gold:
                    papers_with_detected_defects += 1
        paper_results.append(
            {
                "paper_id": paper_id,
                "group": sample.get("group"),
                "system_severe_count": len(review_issues),
                "gold_severe_count": len(gold_issues),
                "true_positive": counts["true_positive"],
                "partial_overlap": counts["partial_overlap"],
                "false_positive": counts["false_positive"],
                "missed": counts["missed"],
                "unresolved": counts["unresolved"],
                "effective_precision": rate(effective_tp, len(review_issues)),
                "effective_recall": rate(effective_tp, len(gold_issues)),
            }
        )

    effective_tp = aggregate["true_positive"] + 0.5 * aggregate["partial_overlap"]
    substantive_tp = (
        aggregate["substantive_true_positive"]
        + 0.5 * aggregate["substantive_partial_overlap"]
    )
    substantive_precision = rate(
        substantive_tp, aggregate["substantive_system_issue_count"]
    )
    substantive_recall = rate(
        substantive_tp, aggregate["substantive_gold_issue_count"]
    )
    location_accuracy = rate(location_correct, location_checked)
    per_paper_detection = rate(papers_with_detected_defects, papers_with_gold_defects)

    gold_complete = not missing_gold_ids and not extra_gold_ids
    reviews_complete = not missing_review_ids and not extra_review_ids
    inputs_complete = not missing_input_ids and len(expected_ids) >= 12
    substantive_entries_complete = substantive_paper_ids <= set(gold_by_id)
    every_substantive_has_gold = substantive_entries_complete and all(
        bool(gold_by_id[paper_id].get("gold_severe_issues"))
        for paper_id in substantive_paper_ids
    )

    audit = gold.get("source_audit")
    audit_valid = isinstance(audit, dict) and all(
        isinstance(audit.get(key), int)
        and not isinstance(audit.get(key), bool)
        and audit.get(key) >= 0
        for key in ("checked_findings", "fabricated_locations", "code_misclassifications")
    )
    audit_pass = (
        audit_valid
        and audit["checked_findings"] >= aggregate["system_issue_count"]
        and audit["fabricated_locations"] == 0
        and audit["code_misclassifications"] == 0
    )

    adjudication_errors = list(dict.fromkeys(errors))
    gates = [
        gate(
            "complete_4_plus_4_plus_4_inputs",
            "pass" if inputs_complete else "incomplete",
            {"sample_count": len(expected_ids), "missing_inputs": missing_input_ids},
            ">=12 declared samples and every source_status=provided",
            "Partial input sets cannot prove blind-test accuracy.",
        ),
        gate(
            "system_review_coverage",
            "pass" if reviews_complete else "incomplete",
            {"missing": missing_review_ids, "extra": extra_review_ids},
            "one system review for every declared sample",
            "Missing reviews cannot enter accuracy metrics.",
        ),
        gate(
            "human_gold_coverage",
            "pass" if gold_complete else "incomplete",
            {"missing": missing_gold_ids, "extra": extra_gold_ids},
            "one post-freeze human-gold entry for every declared sample",
            "Gold conclusions must remain unavailable until reviews are frozen.",
        ),
        gate(
            "gold_accounting",
            "fail" if adjudication_errors else "pass" if gold_complete and reviews_complete else "incomplete",
            {"errors": adjudication_errors, "unresolved": aggregate["unresolved"]},
            "every system and gold severe issue accounted exactly once; 0 unresolved",
            "Partial matches count as 0.5 only after explicit human adjudication.",
        ),
        gate(
            "substantive_gold_presence",
            "pass"
            if every_substantive_has_gold
            else "fail"
            if substantive_entries_complete and gold_complete
            else "incomplete",
            {
                "substantive_samples": len(substantive_paper_ids),
                "papers_with_gold_severe_issues": papers_with_gold_defects,
            },
            "every ordinary/defective or real-draft sample has >=1 human-verified fatal/important issue",
            "The corpus must actually test substantive defect detection.",
        ),
        gate(
            "substantive_issue_recall",
            "pass"
            if substantive_recall is not None and substantive_recall >= 0.80
            else "fail"
            if substantive_recall is not None and gold_complete and reviews_complete
            else "incomplete",
            substantive_recall,
            ">= 0.80 effective recall on ordinary/defective papers and real drafts",
            "A human-adjudicated partial overlap contributes 0.5.",
        ),
        gate(
            "substantive_issue_precision",
            "pass"
            if substantive_precision is not None and substantive_precision >= 0.70
            else "fail"
            if substantive_precision is not None and gold_complete and reviews_complete
            else "incomplete",
            substantive_precision,
            ">= 0.70 effective precision on ordinary/defective papers and real drafts",
            "This prevents passing by reporting many unsupported severe issues.",
        ),
        gate(
            "per_paper_defect_detection",
            "pass"
            if per_paper_detection == 1.0
            else "fail"
            if per_paper_detection is not None and gold_complete and reviews_complete
            else "incomplete",
            per_paper_detection,
            "100% of substantive samples recover at least one human-verified severe issue",
            "Aggregate recall alone may hide a completely missed paper.",
        ),
        gate(
            "accepted_issue_location_accuracy",
            "pass"
            if location_accuracy == 1.0
            else "fail"
            if location_accuracy is not None and gold_complete and reviews_complete
            else "incomplete",
            location_accuracy,
            "100% of accepted severe-issue matches have correct source locations",
            "An issue without a real source location is not a valid finding.",
        ),
        gate(
            "source_audit",
            "pass"
            if audit_pass
            else "fail"
            if audit_valid
            else "incomplete",
            audit,
            "audit covers every system severe issue; 0 fabricated locations and 0 code misclassifications",
            "Source-page inspection cannot be inferred from JSON similarity.",
        ),
    ]
    if aggregate["unresolved"]:
        for item in gates:
            if item["name"] == "gold_accounting":
                item["status"] = "fail"

    statuses = {item["status"] for item in gates}
    overall = "fail" if "fail" in statuses else "incomplete" if "incomplete" in statuses else "pass"
    return {
        "schema_version": "1.0",
        "overall_status": overall,
        "aggregate": {
            "system_severe_count": aggregate["system_issue_count"],
            "gold_severe_count": aggregate["gold_issue_count"],
            "true_positive": aggregate["true_positive"],
            "partial_overlap": aggregate["partial_overlap"],
            "false_positive": aggregate["false_positive"],
            "missed": aggregate["missed"],
            "unresolved": aggregate["unresolved"],
            "effective_precision": rate(effective_tp, aggregate["system_issue_count"]),
            "effective_recall": rate(effective_tp, aggregate["gold_issue_count"]),
            "substantive_effective_precision": substantive_precision,
            "substantive_effective_recall": substantive_recall,
            "per_paper_defect_detection": per_paper_detection,
            "accepted_issue_location_accuracy": location_accuracy,
            "error_attribution": dict(sorted(attribution.items())),
        },
        "gates": gates,
        "papers": paper_results,
        "interpretation_limits": [
            "Human gold must be authored after system reviews are frozen.",
            "Partial overlaps contribute 0.5 only after explicit source-page adjudication.",
            "Agreement and accuracy are separate: also run compare-reviews.py for inter-reviewer consistency.",
            "Revision-pair resolution accuracy is evaluated separately from this issue-detection report.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--system-reviews", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_object(args.manifest)
        reviews, review_errors = collect_reviews(args.system_reviews)
        if review_errors:
            raise ValueError("; ".join(review_errors))
        gold = load_object(args.gold)
        result = evaluate(manifest, reviews, gold)
    except Exception as exc:
        print(f"Blind-result evaluation failed to run: {exc}", file=sys.stderr)
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
