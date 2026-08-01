#!/usr/bin/env python3
"""Validate that a re-review accounts for every prior issue and any new regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


RE_REVIEW_STATUS = {
    "resolved",
    "partially_resolved",
    "unresolved",
    "unverifiable",
}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return value


def normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duplicate_values(values: List[str]) -> List[str]:
    return sorted(value for value, count in Counter(values).items() if value and count > 1)


def validate_pair(
    before: Dict[str, Any],
    after: Dict[str, Any],
    before_path: Path,
    after_path: Path,
    before_paper: Optional[Path],
    after_paper: Optional[Path],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    before_issues = before.get("issues")
    after_issues = after.get("issues")
    after_evidence = after.get("evidence")
    re_review = after.get("re_review")
    if not isinstance(before_issues, list):
        errors.append("Before review issues must be a list.")
        before_issues = []
    if not isinstance(after_issues, list):
        errors.append("After review issues must be a list.")
        after_issues = []
    if not isinstance(after_evidence, list):
        errors.append("After review evidence must be a list.")
        after_evidence = []
    if not isinstance(re_review, list):
        errors.append("After review re_review must be a list.")
        re_review = []

    before_by_id: Dict[str, Dict[str, Any]] = {}
    before_ids: List[str] = []
    for index, issue in enumerate(before_issues, start=1):
        if not isinstance(issue, dict):
            errors.append(f"Before issue row {index} must be an object.")
            continue
        issue_id = normalized(issue.get("id"))
        if not issue_id:
            errors.append(f"Before issue row {index} has no id.")
            continue
        before_ids.append(issue_id)
        before_by_id.setdefault(issue_id, issue)
        if not normalized(issue.get("completion_test")):
            errors.append(f"Before issue {issue_id} has no completion_test to freeze.")
    duplicates = duplicate_values(before_ids)
    if duplicates:
        errors.append("Duplicate before issue ids: " + ", ".join(duplicates))

    after_issue_ids = [
        normalized(issue.get("id"))
        for issue in after_issues
        if isinstance(issue, dict) and normalized(issue.get("id"))
    ]
    duplicates = duplicate_values(after_issue_ids)
    if duplicates:
        errors.append("Duplicate after issue ids: " + ", ".join(duplicates))
    after_issue_id_set = set(after_issue_ids)

    evidence_ids = [
        normalized(item.get("id"))
        for item in after_evidence
        if isinstance(item, dict) and normalized(item.get("id"))
    ]
    duplicates = duplicate_values(evidence_ids)
    if duplicates:
        errors.append("Duplicate after evidence ids: " + ", ".join(duplicates))
    evidence_id_set = set(evidence_ids)

    re_review_ids: List[str] = []
    status_counts = Counter()
    regression_ids: List[str] = []
    for index, item in enumerate(re_review, start=1):
        if not isinstance(item, dict):
            errors.append(f"Re-review row {index} must be an object.")
            continue
        prior_id = normalized(item.get("prior_issue_id"))
        if not prior_id:
            errors.append(f"Re-review row {index} has no prior_issue_id.")
            continue
        re_review_ids.append(prior_id)
        if prior_id not in before_by_id:
            errors.append(f"Re-review row {index} references unknown prior issue {prior_id}.")
            continue

        expected_test = normalized(before_by_id[prior_id].get("completion_test"))
        actual_test = normalized(item.get("prior_completion_test"))
        if actual_test != expected_test:
            errors.append(
                f"Re-review {prior_id} changed the frozen prior_completion_test."
            )

        status = normalized(item.get("status"))
        if status not in RE_REVIEW_STATUS:
            errors.append(f"Re-review {prior_id} has invalid status: {status!r}.")
        else:
            status_counts[status] += 1

        current_evidence_ids = item.get("current_evidence_ids")
        if not isinstance(current_evidence_ids, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in current_evidence_ids or []
        ):
            errors.append(
                f"Re-review {prior_id} current_evidence_ids must be a list of non-empty strings."
            )
            current_evidence_ids = []
        unknown_evidence = sorted(set(current_evidence_ids) - evidence_id_set)
        if unknown_evidence:
            errors.append(
                f"Re-review {prior_id} references unknown current evidence: "
                + ", ".join(unknown_evidence)
            )
        if status in {"resolved", "partially_resolved", "unresolved"} and not current_evidence_ids:
            errors.append(
                f"Re-review {prior_id} status {status} requires current evidence."
            )
        if not normalized(item.get("note")):
            errors.append(f"Re-review {prior_id} requires a non-empty note.")

        if normalized(item.get("new_regression")):
            errors.append(
                f"Re-review {prior_id} uses deprecated new_regression text; "
                "use new_regression_issue_ids."
            )
        item_regressions = item.get("new_regression_issue_ids", [])
        if not isinstance(item_regressions, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in item_regressions or []
        ):
            errors.append(
                f"Re-review {prior_id} new_regression_issue_ids must be a list "
                "of non-empty strings."
            )
            item_regressions = []
        unknown_regressions = sorted(set(item_regressions) - after_issue_id_set)
        if unknown_regressions:
            errors.append(
                f"Re-review {prior_id} references unknown new regression issues: "
                + ", ".join(unknown_regressions)
            )
        regression_ids.extend(item_regressions)

    duplicates = duplicate_values(re_review_ids)
    if duplicates:
        errors.append("Duplicate re-review coverage: " + ", ".join(duplicates))
    missing_prior = sorted(set(before_ids) - set(re_review_ids))
    if missing_prior:
        errors.append("Prior issues omitted from re-review: " + ", ".join(missing_prior))
    duplicate_regressions = duplicate_values(regression_ids)
    if duplicate_regressions:
        errors.append(
            "New regression issues linked more than once: "
            + ", ".join(duplicate_regressions)
        )

    paper_check: Dict[str, Any] = {
        "performed": bool(before_paper or after_paper),
        "before_path": str(before_paper or ""),
        "after_path": str(after_paper or ""),
        "distinct_sha256": None,
    }
    if bool(before_paper) != bool(after_paper):
        errors.append("Provide both --before-paper and --after-paper, or neither.")
    elif before_paper and after_paper:
        if not before_paper.is_file():
            errors.append(f"Before paper does not exist: {before_paper}")
        if not after_paper.is_file():
            errors.append(f"After paper does not exist: {after_paper}")
        if before_paper.is_file() and after_paper.is_file():
            distinct = sha256(before_paper) != sha256(after_paper)
            paper_check["distinct_sha256"] = distinct
            if not distinct:
                errors.append("Before and after papers have identical SHA-256 content.")

    return {
        "schema_version": "1.0",
        "status": "pass" if not errors else "fail",
        "before_review": str(before_path),
        "after_review": str(after_path),
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "prior_issues": len(before_ids),
            "covered_prior_issues": len(set(before_ids) & set(re_review_ids)),
            "resolved": status_counts["resolved"],
            "partially_resolved": status_counts["partially_resolved"],
            "unresolved": status_counts["unresolved"],
            "unverifiable": status_counts["unverifiable"],
            "new_regression_links": len(regression_ids),
        },
        "paper_pair_check": paper_check,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-review", required=True, type=Path)
    parser.add_argument("--after-review", required=True, type=Path)
    parser.add_argument("--before-paper", type=Path)
    parser.add_argument("--after-paper", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        before = load_json(args.before_review)
        after = load_json(args.after_review)
        result = validate_pair(
            before,
            after,
            args.before_review.resolve(),
            args.after_review.resolve(),
            args.before_paper.resolve() if args.before_paper else None,
            args.after_paper.resolve() if args.after_paper else None,
        )
    except Exception as exc:
        print(f"Revision-pair evaluation failed to run: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
