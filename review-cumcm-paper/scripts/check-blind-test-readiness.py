#!/usr/bin/env python3
"""Check blind-test or independent-review manifests for input, leakage, and output readiness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from audit_anonymity import audit_file


SOURCE_STATUS = {"provided", "partial_input", "missing_input"}
FORBIDDEN_KEYS = {
    "expected_answer",
    "gold_conclusion",
    "gold_score",
    "verified_dimension_scores",
    "recalibrated_score_100",
    "critical_issues",
    "positive_examples",
    "negative_examples",
    "candidate_gap",
    "reviewer_notes",
    "corrections_from_automatic_analysis",
    "agreement_status",
}
AWARD_LABEL_RE = re.compile(r"(一等奖|国一|优秀论文|获奖|金奖|银奖|铜奖)")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def walk_keys(value: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{prefix}.{key}" if prefix else str(key)
            yield current
            yield from walk_keys(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_keys(item, f"{prefix}[{index}]")


def resolve_path(value: str, manifest_path: Path) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    from_manifest = manifest_path.parent / candidate
    if from_manifest.exists():
        return from_manifest.resolve()
    return (Path.cwd() / candidate).resolve()


def check_manifest(manifest: Dict[str, Any], manifest_path: Path, phase: str) -> Dict[str, Any]:
    errors: List[str] = []
    blockers: List[str] = []
    warnings: List[str] = []

    if manifest.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'.")
    if manifest.get("kind") not in {"blind_test", "independent_recheck"}:
        errors.append("kind must be 'blind_test' or 'independent_recheck'.")
    if manifest.get("expected_answers_attached") is not False:
        errors.append("expected_answers_attached must be false.")
    if not manifest.get("blindness_rules"):
        errors.append("blindness_rules must be a non-empty list.")

    runtime_status = {
        "required": bool(manifest.get("sanitized_runtime_required")),
        "path": manifest.get("runtime_skill_path", ""),
        "exists": False,
        "stub_present": False,
    }
    if runtime_status["required"]:
        runtime_path = resolve_path(str(runtime_status["path"]), manifest_path)
        runtime_status["exists"] = bool(
            runtime_path and runtime_path.is_dir() and (runtime_path / "SKILL.md").is_file()
        )
        if not runtime_status["exists"]:
            blockers.append("Sanitized runtime skill is missing or lacks SKILL.md.")
        else:
            exemplar = runtime_path / "references/reviewed-exemplars.md"
            if exemplar.is_file():
                content = exemplar.read_text(encoding="utf-8-sig")
                runtime_status["stub_present"] = "BLIND_RUNTIME_STUB" in content
            if not runtime_status["stub_present"]:
                errors.append(
                    "Sanitized runtime does not contain the non-leaking exemplar stub."
                )

    leaked_paths = []
    for path in walk_keys(manifest):
        key = re.sub(r".*\.", "", path)
        key = re.sub(r"\[\d+\]$", "", key)
        if key in FORBIDDEN_KEYS:
            leaked_paths.append(path)
    if leaked_paths:
        errors.append("Manifest contains conclusion-leaking fields: " + ", ".join(leaked_paths))

    required_groups = manifest.get("required_groups")
    if not isinstance(required_groups, dict) or not required_groups:
        errors.append("required_groups must be a non-empty object.")
        required_groups = {}
    else:
        for group, count in required_groups.items():
            if not isinstance(group, str) or not group:
                errors.append("Every required_groups key must be a non-empty string.")
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                errors.append(f"required_groups[{group!r}] must be a positive integer.")

    samples = manifest.get("samples")
    if not isinstance(samples, list):
        errors.append("samples must be a list.")
        samples = []

    ids = [str(item.get("blind_id", "")).strip() for item in samples if isinstance(item, dict)]
    if any(not value for value in ids):
        errors.append("Every sample requires a non-empty blind_id.")
    duplicate_ids = sorted(value for value, count in Counter(ids).items() if value and count > 1)
    if duplicate_ids:
        errors.append("Duplicate blind_id values: " + ", ".join(duplicate_ids))

    group_counts = Counter(str(item.get("group", "")) for item in samples if isinstance(item, dict))
    for group, required in required_groups.items():
        actual = group_counts.get(group, 0)
        if actual != required:
            errors.append(f"Group {group!r} requires exactly {required} slots, found {actual}.")
    extras = sorted(set(group_counts) - set(required_groups))
    if extras:
        errors.append("Samples use undeclared groups: " + ", ".join(extras))

    input_rows = []
    output_rows = []
    anonymization_required = bool(manifest.get("anonymization_required"))
    for index, sample in enumerate(samples, start=1):
        if not isinstance(sample, dict):
            errors.append(f"samples[{index}] must be an object.")
            continue
        sid = str(sample.get("blind_id", "")).strip() or f"row-{index}"
        status = sample.get("source_status")
        if status not in SOURCE_STATUS:
            errors.append(f"{sid} has invalid source_status: {status!r}.")
            continue
        if sample.get("prior_conclusion_exposure") is not False:
            errors.append(f"{sid} must set prior_conclusion_exposure=false.")

        paper_value = str(sample.get("paper_path", "")).strip()
        problem_value = str(sample.get("problem_path", "")).strip()
        paper_path = resolve_path(paper_value, manifest_path)
        problem_path = resolve_path(problem_value, manifest_path)
        paper_exists = bool(paper_path and paper_path.exists())
        problem_exists = bool(problem_path and problem_path.exists())
        attachment_values = [
            str(value).strip() for value in sample.get("attachment_paths", []) or []
        ]
        attachment_paths = [
            resolve_path(value, manifest_path) for value in attachment_values if value
        ]
        missing_attachments = [
            value
            for value, path in zip(attachment_values, attachment_paths)
            if not path or not path.exists()
        ]
        input_rows.append(
            {
                "blind_id": sid,
                "group": sample.get("group"),
                "source_status": status,
                "paper_exists": paper_exists,
                "problem_exists": problem_exists,
                "attachment_count": len(attachment_values),
                "missing_attachments": missing_attachments,
                "anonymity_status": "not_checked",
                "anonymity_findings": [],
                "anonymity_warnings": [],
            }
        )
        input_row = input_rows[-1]

        if anonymization_required and paper_exists and paper_path:
            anonymity = audit_file(paper_path)
            input_row["anonymity_status"] = anonymity["status"]
            input_row["anonymity_findings"] = anonymity["findings"]
            input_row["anonymity_warnings"] = anonymity["warnings"]
            if anonymity["status"] != "pass":
                errors.append(
                    f"{sid}: paper failed anonymity audit: "
                    + "; ".join(anonymity["findings"])
                )
            for warning in anonymity["warnings"]:
                warnings.append(f"{sid}: anonymity audit warning: {warning}")
        elif not anonymization_required:
            input_row["anonymity_status"] = "not_required"

        if status == "provided":
            if not paper_value or not paper_exists:
                blockers.append(f"{sid}: provided paper_path does not exist.")
            if not problem_value or not problem_exists:
                blockers.append(f"{sid}: provided problem_path does not exist.")
            if missing_attachments:
                blockers.append(
                    f"{sid}: listed attachments do not exist: {', '.join(missing_attachments)}"
                )
            if anonymization_required:
                for label, value in (("paper_path", paper_value), ("problem_path", problem_value)):
                    if AWARD_LABEL_RE.search(Path(value).name):
                        errors.append(f"{sid}: {label} leaks an award/exemplar label.")
        elif status == "partial_input":
            if not paper_value and not problem_value and not attachment_values:
                errors.append(
                    f"{sid}: partial_input requires at least one received material path."
                )
            if paper_value and not paper_exists:
                blockers.append(f"{sid}: partial paper_path does not exist.")
            if problem_value and not problem_exists:
                blockers.append(f"{sid}: partial problem_path does not exist.")
            if missing_attachments:
                blockers.append(
                    f"{sid}: listed partial attachments do not exist: "
                    + ", ".join(missing_attachments)
                )
            missing_parts = []
            if not paper_value:
                missing_parts.append("paper")
            if not problem_value:
                missing_parts.append("original problem")
            if not missing_parts and paper_exists and problem_exists and not missing_attachments:
                blockers.append(
                    f"{sid}: all listed core materials exist; confirm necessary attachments "
                    "and mark source_status=provided."
                )
            elif missing_parts:
                blockers.append(
                    f"{sid}: partial input still lacks " + ", ".join(missing_parts) + "."
                )
            if anonymization_required:
                for label, value in (("paper_path", paper_value), ("problem_path", problem_value)):
                    if value and AWARD_LABEL_RE.search(Path(value).name):
                        errors.append(f"{sid}: {label} leaks an award/exemplar label.")
        else:
            if paper_value or problem_value:
                warnings.append(
                    f"{sid}: missing_input slot contains a path; clear it or mark the source provided."
                )
            blockers.append(f"{sid}: source material is still missing.")

        review_a = resolve_path(str(sample.get("reviewer_a_output", "")), manifest_path)
        review_b = resolve_path(str(sample.get("reviewer_b_output", "")), manifest_path)
        adjudication = resolve_path(str(sample.get("adjudication_output", "")), manifest_path)
        output_rows.append(
            {
                "blind_id": sid,
                "reviewer_a_exists": bool(review_a and review_a.is_file()),
                "reviewer_b_exists": bool(review_b and review_b.is_file()),
                "adjudication_exists": bool(adjudication and adjudication.is_file()),
                "reviewer_a_json_valid": None,
                "reviewer_b_json_valid": None,
                "adjudication_json_valid": None,
                "independent_reviewer_ids": None,
            }
        )
        output_row = output_rows[-1]
        if phase == "comparison" and status == "provided":
            expected_id = str(sample.get("paper_id") or sid)
            review_objects: Dict[str, Dict[str, Any]] = {}
            if not review_a or not review_a.is_file():
                blockers.append(f"{sid}: reviewer_a_output is missing.")
            else:
                try:
                    value = load_json(review_a)
                    if not isinstance(value, dict):
                        raise ValueError("root must be an object")
                    identity = str(
                        value.get("metadata", {}).get("paper_id")
                        or value.get("metadata", {}).get("sample_id")
                        or ""
                    )
                    reviewer_id = str(
                        value.get("metadata", {}).get("reviewer_id") or ""
                    ).strip()
                    if identity != expected_id:
                        errors.append(
                            f"{sid}: reviewer A identity {identity!r} does not match {expected_id!r}."
                        )
                    elif not reviewer_id:
                        errors.append(f"{sid}: reviewer A metadata.reviewer_id is missing.")
                    else:
                        output_row["reviewer_a_json_valid"] = True
                        review_objects["a"] = value
                except Exception as exc:
                    output_row["reviewer_a_json_valid"] = False
                    errors.append(f"{sid}: reviewer A JSON is invalid: {exc}.")
            if not review_b or not review_b.is_file():
                blockers.append(f"{sid}: reviewer_b_output is missing.")
            else:
                try:
                    value = load_json(review_b)
                    if not isinstance(value, dict):
                        raise ValueError("root must be an object")
                    identity = str(
                        value.get("metadata", {}).get("paper_id")
                        or value.get("metadata", {}).get("sample_id")
                        or ""
                    )
                    reviewer_id = str(
                        value.get("metadata", {}).get("reviewer_id") or ""
                    ).strip()
                    if identity != expected_id:
                        errors.append(
                            f"{sid}: reviewer B identity {identity!r} does not match {expected_id!r}."
                        )
                    elif not reviewer_id:
                        errors.append(f"{sid}: reviewer B metadata.reviewer_id is missing.")
                    else:
                        output_row["reviewer_b_json_valid"] = True
                        review_objects["b"] = value
                except Exception as exc:
                    output_row["reviewer_b_json_valid"] = False
                    errors.append(f"{sid}: reviewer B JSON is invalid: {exc}.")
            if "a" in review_objects and "b" in review_objects:
                reviewer_a_id = str(
                    review_objects["a"].get("metadata", {}).get("reviewer_id")
                )
                reviewer_b_id = str(
                    review_objects["b"].get("metadata", {}).get("reviewer_id")
                )
                independent = reviewer_a_id != reviewer_b_id
                output_row["independent_reviewer_ids"] = independent
                if not independent:
                    errors.append(
                        f"{sid}: reviewer A and B use the same reviewer_id {reviewer_a_id!r}."
                    )
            if not adjudication or not adjudication.is_file():
                blockers.append(f"{sid}: adjudication_output is missing.")
            else:
                try:
                    value = load_json(adjudication)
                    if not isinstance(value, dict):
                        raise ValueError("root must be an object")
                    papers = value.get("papers")
                    if not isinstance(papers, list):
                        raise ValueError("papers must be a list")
                    paper_ids = {
                        str(item.get("paper_id"))
                        for item in papers
                        if isinstance(item, dict) and item.get("paper_id")
                    }
                    if expected_id not in paper_ids:
                        errors.append(
                            f"{sid}: adjudication has no entry for {expected_id!r}."
                        )
                    else:
                        output_row["adjudication_json_valid"] = True
                except Exception as exc:
                    output_row["adjudication_json_valid"] = False
                    errors.append(f"{sid}: adjudication JSON is invalid: {exc}.")

    manifest_valid = not errors
    intake_ready = manifest_valid and not any(
        row["source_status"] != "provided"
        or not row["paper_exists"]
        or not row["problem_exists"]
        or bool(row["missing_attachments"])
        or anonymization_required and row["anonymity_status"] != "pass"
        for row in input_rows
    ) and (not runtime_status["required"] or runtime_status["exists"] and runtime_status["stub_present"])
    comparison_ready = intake_ready and all(
        row["reviewer_a_exists"]
        and row["reviewer_b_exists"]
        and row["adjudication_exists"]
        and row["reviewer_a_json_valid"] is True
        and row["reviewer_b_json_valid"] is True
        and row["adjudication_json_valid"] is True
        and row["independent_reviewer_ids"] is True
        for row in output_rows
    )
    requested_ready = intake_ready if phase == "intake" else comparison_ready
    if not manifest_valid:
        status = "invalid"
    elif requested_ready:
        status = "ready"
    else:
        status = "incomplete"

    return {
        "schema_version": "1.0",
        "manifest_kind": manifest.get("kind"),
        "phase": phase,
        "status": status,
        "manifest_valid": manifest_valid,
        "intake_ready": intake_ready,
        "comparison_ready": comparison_ready,
        "errors": errors,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "runtime_skill": runtime_status,
        "counts": {
            "required_groups": required_groups,
            "actual_groups": dict(group_counts),
            "sample_slots": len(samples),
            "provided_inputs": sum(row["source_status"] == "provided" for row in input_rows),
            "partial_inputs": sum(
                row["source_status"] == "partial_input" for row in input_rows
            ),
            "complete_input_pairs": sum(
                row["paper_exists"] and row["problem_exists"] for row in input_rows
            ),
            "complete_review_pairs": sum(
                row["reviewer_a_exists"] and row["reviewer_b_exists"] for row in output_rows
            ),
            "completed_adjudications": sum(
                row["adjudication_exists"] for row in output_rows
            ),
            "valid_review_pairs": sum(
                row["reviewer_a_json_valid"] is True
                and row["reviewer_b_json_valid"] is True
                and row["independent_reviewer_ids"] is True
                for row in output_rows
            ),
            "valid_adjudications": sum(
                row["adjudication_json_valid"] is True for row in output_rows
            ),
        },
        "input_rows": input_rows,
        "output_rows": output_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--phase", choices=("intake", "comparison"), default="intake")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        manifest = load_json(args.manifest)
        if not isinstance(manifest, dict):
            raise ValueError("Manifest root must be an object.")
        result = check_manifest(manifest, args.manifest.resolve(), args.phase)
    except Exception as exc:
        print(f"Readiness check failed to run: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
