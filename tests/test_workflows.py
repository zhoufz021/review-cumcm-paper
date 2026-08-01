from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Optional
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "review-cumcm-paper/scripts"
FIXTURE = ROOT / "tests/fixtures/valid-review.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def make_pdf(path: Path, *, with_identity: bool = True) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    if with_identity:
        writer.add_metadata(
            {"/Author": "Synthetic Author", "/Title": "Synthetic Paper"}
        )
    with path.open("wb") as stream:
        writer.write(stream)


def make_docx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>问题一：建立模型并给出结果。</w:t></w:r></w:p><w:sectPr/></w:body>
</w:document>"""
    core = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Synthetic Author</dc:creator></cp:coreProperties>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)


class WorkflowSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="review-cumcm-workflow-")
        self.temp = Path(self.temporary.name)
        self.base_review = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.first_evidence_id = self.base_review["evidence"][0]["id"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(
        self, name: str, *args: object, expected: tuple[int, ...] = (0,)
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=90,
        )
        self.assertIn(completed.returncode, expected, completed.stdout)
        return completed

    def make_review(
        self, paper_id: str, reviewer_id: str, issue_id: Optional[str] = None
    ) -> dict:
        review = deepcopy(self.base_review)
        review.setdefault("metadata", {})["paper_id"] = paper_id
        review["metadata"]["reviewer_id"] = reviewer_id
        if issue_id:
            review["issues"] = [
                {
                    "id": issue_id,
                    "severity": "important",
                    "dimension": "验证与稳健性",
                    "subproblem_ids": ["Q1"],
                    "evidence_ids": [self.first_evidence_id],
                    "location": "PDF文件页序 p.1",
                    "fact": "缺少独立验证。",
                    "judgment": "结果可信度不足。",
                    "inference": "",
                    "impact": "可能掩盖过拟合。",
                    "recommendation": "补充独立验证。",
                    "completion_test": "给出独立数据上的验证指标。",
                    "confidence": "high",
                }
            ]
        return review

    def test_pdf_docx_sanitization_extraction_and_structure(self) -> None:
        source_pdf = self.temp / "source.pdf"
        sanitized_pdf = self.temp / "paper.pdf"
        make_pdf(source_pdf)
        self.run_script(
            "audit_anonymity.py", "--file", source_pdf, expected=(1,)
        )
        self.run_script(
            "sanitize_blind_paper.py",
            "--input",
            source_pdf,
            "--output",
            sanitized_pdf,
            "--report",
            self.temp / "sanitize-pdf.json",
        )
        self.run_script("audit_anonymity.py", "--file", sanitized_pdf)

        source_docx = self.temp / "source.docx"
        sanitized_docx = self.temp / "paper.docx"
        make_docx(source_docx)
        self.run_script(
            "audit_anonymity.py", "--file", source_docx, expected=(1,)
        )
        self.run_script(
            "sanitize_blind_paper.py",
            "--input",
            source_docx,
            "--output",
            sanitized_docx,
            "--report",
            self.temp / "sanitize-docx.json",
        )
        self.run_script("audit_anonymity.py", "--file", sanitized_docx)
        docx_extraction = self.temp / "docx-extraction.json"
        self.run_script(
            "extract-paper.py",
            "--input",
            sanitized_docx,
            "--output",
            docx_extraction,
        )
        self.assertIn("问题一", docx_extraction.read_text(encoding="utf-8"))

        paper = self.temp / "paper.md"
        paper.write_text(
            "# 摘要\n\n## 问题一\n建立模型并给出结果。\n", encoding="utf-8"
        )
        extraction = self.temp / "paper-extraction.json"
        self.run_script(
            "extract-paper.py", "--input", paper, "--output", extraction
        )
        problem_index = self.temp / "problem-index.json"
        write_json(problem_index, self.base_review["problem_index"])
        structure = self.temp / "structure.json"
        self.run_script(
            "check-structure.py",
            "--problem-index",
            problem_index,
            "--paper-extraction",
            extraction,
            "--output",
            structure,
        )
        structure_result = json.loads(structure.read_text(encoding="utf-8"))
        self.assertEqual(structure_result["authoritative_subproblem_count"], 5)
        self.assertEqual(structure_result["subproblem_source"], "problem_index_only")

    def test_blind_runtime_and_readiness(self) -> None:
        runtime = self.temp / "runtime" / "review-cumcm-paper"
        self.run_script("build-blind-runtime.py", "--output", runtime)
        self.assertIn(
            "BLIND_RUNTIME_STUB",
            (runtime / "references/reviewed-exemplars.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((runtime / "requirements.txt").is_file())

        source_pdf = self.temp / "source.pdf"
        paper_pdf = self.temp / "paper.pdf"
        problem = self.temp / "problem.md"
        make_pdf(source_pdf)
        problem.write_text("# A题\n\n问题一：给出模型结果。\n", encoding="utf-8")
        self.run_script(
            "sanitize_blind_paper.py",
            "--input",
            source_pdf,
            "--output",
            paper_pdf,
        )

        review_a = self.temp / "review-a.json"
        review_b = self.temp / "review-b.json"
        write_json(review_a, self.make_review("B01", "reviewer-a"))
        write_json(review_b, self.make_review("B01", "reviewer-b"))
        adjudication = self.temp / "adjudication.json"
        write_json(
            adjudication,
            {
                "schema_version": "1.0",
                "papers": [
                    {
                        "paper_id": "B01",
                        "issue_matches": [],
                        "unmatched_a": [],
                        "unmatched_b": [],
                    }
                ],
                "source_audit": {
                    "checked_findings": 0,
                    "fabricated_locations": 0,
                    "code_misclassifications": 0,
                },
            },
        )
        manifest = self.temp / "manifest.json"
        write_json(
            manifest,
            {
                "schema_version": "1.0",
                "kind": "independent_recheck",
                "expected_answers_attached": False,
                "anonymization_required": True,
                "sanitized_runtime_required": True,
                "runtime_skill_path": str(runtime),
                "blindness_rules": ["Use only the supplied synthetic inputs."],
                "required_groups": {"blind_pool": 1},
                "samples": [
                    {
                        "blind_id": "B01",
                        "paper_id": "B01",
                        "group": "blind_pool",
                        "source_status": "provided",
                        "paper_path": str(paper_pdf),
                        "problem_path": str(problem),
                        "attachment_paths": [],
                        "prior_conclusion_exposure": False,
                        "reviewer_a_output": str(review_a),
                        "reviewer_b_output": str(review_b),
                        "adjudication_output": str(adjudication),
                    }
                ],
            },
        )
        for phase in ("intake", "comparison"):
            output = self.temp / f"{phase}.json"
            self.run_script(
                "check-blind-test-readiness.py",
                "--manifest",
                manifest,
                "--phase",
                phase,
                "--output",
                output,
            )
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["status"], "ready"
            )

    def test_revision_pair_gate(self) -> None:
        before = deepcopy(self.base_review)
        before["issues"] = [{"id": "I01", "completion_test": "补充独立验证。"}]
        after = deepcopy(self.base_review)
        after["re_review"] = [
            {
                "prior_issue_id": "I01",
                "prior_completion_test": "补充独立验证。",
                "current_evidence_ids": [self.first_evidence_id],
                "status": "resolved",
                "note": "合成测试中已补充证据。",
                "new_regression_issue_ids": [],
            }
        ]
        before_review = self.temp / "before-review.json"
        after_review = self.temp / "after-review.json"
        before_paper = self.temp / "before.md"
        after_paper = self.temp / "after.md"
        output = self.temp / "revision-result.json"
        write_json(before_review, before)
        write_json(after_review, after)
        before_paper.write_text("修改前论文", encoding="utf-8")
        after_paper.write_text("修改后论文", encoding="utf-8")
        self.run_script(
            "evaluate-revision-pairs.py",
            "--before-review",
            before_review,
            "--after-review",
            after_review,
            "--before-paper",
            before_paper,
            "--after-paper",
            after_paper,
            "--output",
            output,
        )
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8"))["status"], "pass"
        )

    def test_twelve_pair_review_comparison(self) -> None:
        reviews_a = self.temp / "reviews-a"
        reviews_b = self.temp / "reviews-b"
        reviews_a.mkdir()
        reviews_b.mkdir()
        paper_ids = [f"B{i:02d}" for i in range(1, 13)]
        for paper_id in paper_ids:
            write_json(
                reviews_a / f"{paper_id}.json",
                self.make_review(paper_id, "reviewer-a", "I01"),
            )
            write_json(
                reviews_b / f"{paper_id}.json",
                self.make_review(paper_id, "reviewer-b", "J01"),
            )
        adjudication = self.temp / "adjudication.json"
        write_json(
            adjudication,
            {
                "schema_version": "1.0",
                "papers": [
                    {
                        "paper_id": paper_id,
                        "issue_matches": [
                            {
                                "reviewer_a_issue_id": "I01",
                                "reviewer_b_issue_id": "J01",
                                "verdict": "same_issue",
                                "location_match": True,
                                "decision": "合成测试中的人工回查裁决。",
                            }
                        ],
                        "unmatched_a": [],
                        "unmatched_b": [],
                    }
                    for paper_id in paper_ids
                ],
                "source_audit": {
                    "checked_findings": 12,
                    "fabricated_locations": 0,
                    "code_misclassifications": 0,
                },
            },
        )
        output = self.temp / "comparison.json"
        self.run_script(
            "compare-reviews.py",
            "--review-a",
            reviews_a,
            "--review-b",
            reviews_b,
            "--adjudication",
            adjudication,
            "--output",
            output,
        )
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["overall_status"], "pass")
        self.assertEqual(result["pair_count"], 12)

    def test_blind_accuracy_evaluation(self) -> None:
        system_reviews = self.temp / "system-reviews"
        system_reviews.mkdir()
        paper_ids = [f"B{i:02d}" for i in range(1, 13)]
        groups = {
            **{paper_id: "excellent_unseen" for paper_id in paper_ids[:4]},
            **{paper_id: "ordinary_or_defective" for paper_id in paper_ids[4:8]},
            **{paper_id: "real_draft" for paper_id in paper_ids[8:]},
        }
        for paper_id in paper_ids:
            issue_id = None if groups[paper_id] == "excellent_unseen" else "I01"
            write_json(
                system_reviews / f"{paper_id}.json",
                self.make_review(paper_id, "reviewer-a", issue_id),
            )
        manifest = self.temp / "administrator-manifest.json"
        write_json(
            manifest,
            {
                "required_groups": {
                    "excellent_unseen": 4,
                    "ordinary_or_defective": 4,
                    "real_draft": 4,
                },
                "samples": [
                    {
                        "blind_id": paper_id,
                        "group": groups[paper_id],
                        "source_status": "provided",
                    }
                    for paper_id in paper_ids
                ],
            },
        )
        gold_papers = []
        for paper_id in paper_ids:
            if groups[paper_id] == "excellent_unseen":
                gold_papers.append(
                    {
                        "paper_id": paper_id,
                        "gold_severe_issues": [],
                        "system_issue_assessments": [],
                        "missed_gold_issues": [],
                    }
                )
            else:
                gold_papers.append(
                    {
                        "paper_id": paper_id,
                        "gold_severe_issues": [
                            {
                                "id": "G01",
                                "severity": "important",
                                "dimension": "验证与稳健性",
                                "location": "PDF文件页序 p.1",
                                "description": "合成的人工核验问题。",
                            }
                        ],
                        "system_issue_assessments": [
                            {
                                "system_issue_id": "I01",
                                "gold_issue_id": "G01",
                                "verdict": "true_positive",
                                "location_accurate": True,
                                "error_source": "none",
                                "note": "",
                            }
                        ],
                        "missed_gold_issues": [],
                    }
                )
        gold = self.temp / "human-gold.json"
        write_json(
            gold,
            {
                "papers": gold_papers,
                "source_audit": {
                    "checked_findings": 8,
                    "fabricated_locations": 0,
                    "code_misclassifications": 0,
                },
            },
        )
        output = self.temp / "blind-results.json"
        self.run_script(
            "evaluate-blind-results.py",
            "--manifest",
            manifest,
            "--system-reviews",
            system_reviews,
            "--gold",
            gold,
            "--output",
            output,
        )
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["overall_status"], "pass")
        self.assertEqual(result["aggregate"]["substantive_effective_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
