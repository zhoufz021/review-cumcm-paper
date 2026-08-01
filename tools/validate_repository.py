#!/usr/bin/env python3
"""Validate the public repository and bundled review-cumcm-paper Skill."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "review-cumcm-paper"

EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "assets/review-report-template.md",
    "requirements.txt",
    "references/blind-test-protocol.md",
    "references/dimension-rubrics.md",
    "references/evidence-policy.md",
    "references/output-schema.md",
    "references/problem-type-guides.md",
    "references/reviewed-exemplars.md",
    "references/review-workflow.md",
    "scripts/audit_anonymity.py",
    "scripts/build-blind-runtime.py",
    "scripts/build-review-report.py",
    "scripts/check-blind-test-readiness.py",
    "scripts/check-evidence-consistency.py",
    "scripts/check-structure.py",
    "scripts/compare-reviews.py",
    "scripts/evaluate-blind-results.py",
    "scripts/evaluate-revision-pairs.py",
    "scripts/extract-paper.py",
    "scripts/sanitize_blind_paper.py",
}

REQUIRED_REPOSITORY_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE.md",
    "README.md",
    "SECURITY.md",
    "requirements.txt",
    "docs/DEVELOPMENT.md",
    "docs/RELEASE.md",
    "docs/USAGE.md",
    "examples/prompts.md",
    "tests/fixtures/valid-review.json",
    "tests/test_functional.py",
    "tests/test_repository.py",
    "tests/test_workflows.py",
    "tools/build_release.py",
    "tools/validate_repository.py",
    ".github/workflows/validate.yml",
    ".github/workflows/release.yml",
    ".github/release.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
}

REQUIRED_REFERENCES = {
    "review-workflow.md",
    "evidence-policy.md",
    "problem-type-guides.md",
    "dimension-rubrics.md",
    "reviewed-exemplars.md",
    "blind-test-protocol.md",
    "output-schema.md",
}

FORBIDDEN_FILE_SUFFIXES = {
    ".doc",
    ".docx",
    ".pdf",
    ".xls",
    ".xlsx",
    ".csv",
    ".tsv",
    ".pem",
    ".key",
}

LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def relative_files(base: Path) -> set[str]:
    result = set()
    for path in base.rglob("*"):
        relative = path.relative_to(base)
        if (
            path.is_file()
            and ".git" not in relative.parts
            and "dist" not in relative.parts
            and "__pycache__" not in relative.parts
            and path.suffix not in {".pyc", ".pyo"}
        ):
            result.add(relative.as_posix())
    return result


def add_error(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def iter_markdown_files() -> Iterable[Path]:
    for path in ROOT.rglob("*.md"):
        if ".git" not in path.parts and "dist" not in path.parts:
            yield path


def check_links(errors: list[str]) -> int:
    broken: list[str] = []
    for markdown in iter_markdown_files():
        content = markdown.read_text(encoding="utf-8-sig")
        for raw_target in LINK_PATTERN.findall(content):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            if not (markdown.parent / target).resolve().exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {raw_target}")
    if broken:
        errors.append("Broken Markdown links: " + "; ".join(broken[:10]))
    return len(broken)


def validate_scripts(errors: list[str], run_help: bool) -> tuple[int, int]:
    scripts = sorted((SKILL / "scripts").glob("*.py"))
    syntax_failures = 0
    help_failures = 0
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    for script in scripts:
        try:
            ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        except SyntaxError as exc:
            syntax_failures += 1
            errors.append(f"Python syntax error in {script.name}: {exc}")
            continue
        if run_help:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if completed.returncode != 0:
                help_failures += 1
                errors.append(
                    f"{script.name} --help exited {completed.returncode}: "
                    + completed.stdout[-500:]
                )
    return syntax_failures, help_failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-cli-help",
        action="store_true",
        help="Skip executing every bundled script with --help.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    add_error(errors, SKILL.is_dir(), "Missing review-cumcm-paper directory.")
    if not SKILL.is_dir():
        print(json.dumps({"status": "fail", "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    actual_skill_files = relative_files(SKILL)
    missing_skill = sorted(EXPECTED_SKILL_FILES - actual_skill_files)
    extra_skill = sorted(actual_skill_files - EXPECTED_SKILL_FILES)
    add_error(errors, not missing_skill, f"Missing Skill files: {missing_skill}")
    add_error(errors, not extra_skill, f"Unexpected Skill files: {extra_skill}")

    repository_files = relative_files(ROOT)
    missing_repository = sorted(REQUIRED_REPOSITORY_FILES - repository_files)
    add_error(errors, not missing_repository, f"Missing repository files: {missing_repository}")

    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(skill_text)
    add_error(
        errors,
        set(frontmatter) == {"name", "description"},
        "SKILL.md frontmatter must contain only name and description.",
    )
    add_error(
        errors,
        frontmatter.get("name") == "review-cumcm-paper",
        "SKILL.md name must be review-cumcm-paper.",
    )
    add_error(errors, bool(frontmatter.get("description")), "SKILL.md description is empty.")
    add_error(errors, len(skill_text.splitlines()) < 500, "SKILL.md must stay below 500 lines.")
    add_error(
        errors,
        "# 审核 CUMCM 数学建模论文" in skill_text,
        "SKILL.md must contain the Chinese main title.",
    )

    for reference in REQUIRED_REFERENCES:
        add_error(
            errors,
            f"references/{reference}" in skill_text,
            f"SKILL.md does not link references/{reference}.",
        )
    add_error(
        errors,
        "assets/review-report-template.md" in skill_text,
        "SKILL.md does not link the report template.",
    )

    skill_requirements = (SKILL / "requirements.txt").read_text(encoding="utf-8")
    add_error(
        errors,
        bool(re.search(r"(?m)^pdfplumber>=0\.11,<0\.12$", skill_requirements)),
        "Installable Skill requirements must pin the tested pdfplumber range.",
    )
    add_error(
        errors,
        bool(re.search(r"(?m)^pypdf>=6,<7$", skill_requirements)),
        "Installable Skill requirements must pin the tested pypdf range.",
    )
    root_requirement_lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    add_error(
        errors,
        root_requirement_lines == ["-r review-cumcm-paper/requirements.txt"],
        "Root requirements.txt must delegate to the installable Skill requirements.",
    )

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    license_placeholder = "The repository " + "owner"
    add_error(
        errors,
        license_placeholder not in license_text,
        "LICENSE still contains the repository-owner placeholder.",
    )
    add_error(
        errors,
        bool(re.search(r"(?m)^Copyright \(c\) 20\d{2} .+", license_text)),
        "LICENSE must identify a copyright holder.",
    )

    long_references_without_toc = []
    for reference in sorted((SKILL / "references").glob("*.md")):
        content = reference.read_text(encoding="utf-8")
        if len(content.splitlines()) > 100 and "\n## 目录\n" not in content:
            long_references_without_toc.append(reference.name)
    add_error(
        errors,
        not long_references_without_toc,
        "Reference files longer than 100 lines require a table of contents: "
        + ", ".join(long_references_without_toc),
    )

    metadata_text = (SKILL / "agents/openai.yaml").read_text(encoding="utf-8")
    for field in ("display_name:", "short_description:", "default_prompt:"):
        add_error(errors, field in metadata_text, f"agents/openai.yaml lacks {field}")
    add_error(
        errors,
        "$review-cumcm-paper" in metadata_text,
        "agents/openai.yaml default prompt does not invoke the Skill.",
    )

    forbidden_files = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and "dist" not in path.parts
        and ".git" not in path.parts
        and path.suffix.lower() in FORBIDDEN_FILE_SUFFIXES
    ]
    add_error(errors, not forbidden_files, f"Private or binary source files found: {forbidden_files}")

    absolute_path_hits: list[str] = []
    secret_hits: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "dist" in path.parts or ".git" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".py", ".yaml", ".yml", ".json", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if re.search(r"(?i)(?:^|[\s'\"])[A-Z]:[\\/](?:Users|home|workspace|tmp)[\\/]", text):
            absolute_path_hits.append(path.relative_to(ROOT).as_posix())
        if re.search(r"sk-[A-Za-z0-9_-]{20,}|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", text):
            secret_hits.append(path.relative_to(ROOT).as_posix())
    add_error(errors, not absolute_path_hits, f"Machine-specific paths found: {absolute_path_hits}")
    add_error(errors, not secret_hits, f"Potential secrets found: {secret_hits}")

    unpinned_actions: list[str] = []
    workflow_directory = ROOT / ".github/workflows"
    workflows = sorted(
        [*workflow_directory.glob("*.yml"), *workflow_directory.glob("*.yaml")]
    )
    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.search(r"\buses:\s*([^\s@]+)@([^\s#]+)", line)
            if not match or match.group(1).startswith("./"):
                continue
            if not re.fullmatch(r"[0-9a-f]{40}", match.group(2)):
                unpinned_actions.append(
                    f"{workflow.relative_to(ROOT).as_posix()}:{line_number} -> {match.group(0)}"
                )
    add_error(
        errors,
        not unpinned_actions,
        "GitHub Actions must be pinned to full commit SHAs: "
        + "; ".join(unpinned_actions),
    )

    broken_links = check_links(errors)
    syntax_failures, help_failures = validate_scripts(errors, not args.skip_cli_help)

    summary = {
        "status": "pass" if not errors else "fail",
        "skill_files": len(actual_skill_files),
        "repository_files": len(repository_files),
        "skill_lines": len(skill_text.splitlines()),
        "references": len(list((SKILL / "references").glob("*.md"))),
        "scripts": len(list((SKILL / "scripts").glob("*.py"))),
        "long_references_without_toc": long_references_without_toc,
        "unpinned_actions": unpinned_actions,
        "broken_links": broken_links,
        "syntax_failures": syntax_failures,
        "cli_help_failures": help_failures,
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
