from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "review-cumcm-paper/scripts"
FIXTURE = ROOT / "tests/fixtures/valid-review.json"


class FunctionalSmokeTests(unittest.TestCase):
    def run_script(self, name: str, *args: object) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )

    def test_valid_review_passes_and_builds_report(self) -> None:
        check = self.run_script("check-evidence-consistency.py", "--review", FIXTURE)
        self.assertEqual(check.returncode, 0, check.stdout)
        payload = json.loads(check.stdout)
        self.assertTrue(payload["valid"])

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            build = self.run_script(
                "build-review-report.py", "--review", FIXTURE, "--output", report
            )
            self.assertEqual(build.returncode, 0, build.stdout)
            content = report.read_text(encoding="utf-8")
            self.assertIn("## 十二维评分", content)
            self.assertIn("不是官方竞赛分数", content)

    def test_missing_dimension_is_rejected(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["dimensions"] = payload["dimensions"][:-1]
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            check = self.run_script(
                "check-evidence-consistency.py", "--review", invalid
            )
        self.assertEqual(check.returncode, 1, check.stdout)
        result = json.loads(check.stdout)
        self.assertFalse(result["valid"])

    def test_text_extraction_and_legacy_doc_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            text_file = Path(directory) / "paper.txt"
            text_file.write_text("问题一\n建立模型并给出结果。", encoding="utf-8")
            extracted = self.run_script(
                "extract-paper.py", "--input", text_file, "--compact"
            )
            self.assertEqual(extracted.returncode, 0, extracted.stdout)
            payload = json.loads(extracted.stdout)
            self.assertEqual(payload["format"], "txt")

            legacy = Path(directory) / "legacy.doc"
            legacy.write_bytes(b"synthetic legacy fixture")
            rejected = self.run_script(
                "extract-paper.py", "--input", legacy, "--compact"
            )
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("not supported", rejected.stdout)


if __name__ == "__main__":
    unittest.main()
