#!/usr/bin/env python3
"""Find structure candidates without inferring the problem's subproblem count."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


SECTION_PATTERNS = {
    "abstract": r"摘要",
    "keywords": r"关键词",
    "problem_restatement": r"问题.{0,3}(重述|背景)",
    "problem_analysis": r"问题分析",
    "assumptions": r"(模型)?假设",
    "symbols": r"符号(说明|定义)",
    "model": r"模型.{0,3}(建立|构建)",
    "solution": r"(模型.{0,3})?(求解|算法)",
    "results": r"(结果|方案)",
    "validation": r"(验证|检验|误差分析|敏感性|稳健|鲁棒)",
    "conclusion": r"(结论|总结)",
    "references": r"参考文献",
    "appendix": r"附录",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def records(extraction: Dict[str, Any]) -> Iterable[Tuple[str, str]]:
    for page in extraction.get("pages", []):
        page_number = page.get("file_page", page.get("page"))
        location = page.get("location") or f"page {page_number}"
        yield location, page.get("text", "")
    for paragraph in extraction.get("paragraphs", []):
        yield paragraph.get("location", f"DOCX paragraph {paragraph.get('paragraph')}"), paragraph.get(
            "text", ""
        )
    for line in extraction.get("lines", []):
        yield line.get("location", f"text line {line.get('line')}"), line.get("text", "")


def problem_index(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get("problem_index", [])
        return value if isinstance(value, list) else []
    return []


def label_patterns(item: Dict[str, Any]) -> List[re.Pattern[str]]:
    terms = []
    label = str(item.get("label", "")).strip()
    if label:
        flexible = r"\s*".join(re.escape(part) for part in re.findall(r"\D+|\d+", label))
        terms.append(flexible)
    identifier_value = str(item.get("id", "")).strip()
    if identifier_value:
        terms.append(re.escape(identifier_value))
    identifier = str(item.get("id", ""))
    match = re.fullmatch(r"Q(\d+)", identifier, re.I)
    if match:
        number = match.group(1)
        chinese_numbers = {
            "1": "一",
            "2": "二",
            "3": "三",
            "4": "四",
            "5": "五",
            "6": "六",
            "7": "七",
            "8": "八",
            "9": "九",
            "10": "十",
        }
        variants = [re.escape(number)]
        if number in chinese_numbers:
            variants.append(chinese_numbers[number])
        number_pattern = "(?:" + "|".join(variants) + ")"
        terms.extend(
            [
                rf"问题\s*{number_pattern}",
                rf"问题\s*[（(]?\s*{number_pattern}\s*[）)]?",
                rf"第\s*{number_pattern}\s*问",
            ]
        )
    return [re.compile(term, re.I) for term in dict.fromkeys(terms)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem-index", type=Path, required=True)
    parser.add_argument("--paper-extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        pindex = problem_index(load_json(args.problem_index))
        extraction = load_json(args.paper_extraction)
    except Exception as exc:
        print(f"Failed to read inputs: {exc}", file=sys.stderr)
        return 2

    all_records = list(records(extraction))
    section_candidates: Dict[str, List[str]] = {}
    for section, pattern in SECTION_PATTERNS.items():
        regex = re.compile(pattern, re.I)
        section_candidates[section] = [
            location for location, text in all_records if regex.search(text)
        ][:20]

    subproblem_candidates = []
    for item in pindex:
        patterns = label_patterns(item)
        hits = []
        for location, text in all_records:
            if any(pattern.search(text) for pattern in patterns):
                hits.append(location)
        subproblem_candidates.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "candidate_locations": list(dict.fromkeys(hits))[:30],
                "interpretation": "candidate_only_not_coverage_proof",
            }
        )

    warnings = [
        "Candidate locations do not prove that a subproblem is answered.",
        "The script never infers new subproblems from paper headings, code, figures, tables, or appendices.",
    ]
    if not pindex:
        warnings.append(
            "The authoritative problem index is empty. Subproblem count and coverage are unverifiable."
        )
    if extraction.get("extraction_status") == "sparse_text":
        warnings.append(
            "The paper extraction is sparse. Render or OCR relevant pages before treating missing candidates "
            "as absent content."
        )
    if "ocr" in str(extraction.get("extraction_status", "")).lower():
        warnings.append(
            "The paper ledger comes from OCR. Visually inspect every page used for an important finding; "
            "OCR misses or garbles do not prove absence."
        )

    output = {
        "schema_version": "1.0",
        "authoritative_subproblem_count": len(pindex),
        "subproblem_source": "problem_index_only",
        "section_candidates": section_candidates,
        "subproblem_candidates": subproblem_candidates,
        "warnings": warnings,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
