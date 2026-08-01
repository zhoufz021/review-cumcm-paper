#!/usr/bin/env python3
"""Audit a blind-review paper for identity-bearing metadata and obvious visible identifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


AWARD_LABEL_RE = re.compile(r"(一等奖|国一|优秀论文|获奖|金奖|银奖|铜奖)")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
TEAM_ID_RE = re.compile(
    r"(?:Team\s*#?|队号|参赛队号|队伍编号)\s*[:：#]?\s*"
    r"(?=[A-Z0-9-]*\d{4})[A-Z0-9-]{5,}",
    re.IGNORECASE,
)
GENERIC_PDF_APP_RE = re.compile(
    r"(Microsoft|Word|WPS|Adobe|Acrobat|LaTeX|pdfTeX|LibreOffice|"
    r"pypdf|Foxit|Print\s+To\s+PDF|Quartz|Ghostscript)",
    re.IGNORECASE,
)
PDF_ALWAYS_SENSITIVE = {
    "/Author",
    "/Title",
    "/Subject",
    "/Keywords",
    "/Comments",
    "/Company",
    "/Manager",
}
PDF_ALLOWED_KEYS = {
    "/Creator",
    "/Producer",
    "/CreationDate",
    "/ModDate",
    "/Trapped",
    "/SourceModified",
}
DOCX_CORE_SENSITIVE = {
    "creator",
    "lastModifiedBy",
    "title",
    "subject",
    "keywords",
    "description",
    "category",
    "contentStatus",
}
TRACKED_CHANGE_TAGS = {
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "customXmlInsRangeStart",
    "customXmlDelRangeStart",
    "customXmlMoveFromRangeStart",
    "customXmlMoveToRangeStart",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def nonempty(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (list, tuple, set)):
        return any(nonempty(item) for item in value)
    if isinstance(value, dict):
        return any(nonempty(item) for item in value.values())
    return bool(str(value).strip())


def visible_identifier_findings(text: str) -> List[str]:
    findings: List[str] = []
    emails = sorted(set(EMAIL_RE.findall(text)))
    if emails:
        findings.append("visible email address: " + ", ".join(emails[:5]))
    team_ids = sorted(set(match.group(0) for match in TEAM_ID_RE.finditer(text)))
    if team_ids:
        findings.append("visible team identifier: " + ", ".join(team_ids[:5]))
    return findings


def iter_docx_xml(zip_file: ZipFile) -> Iterable[tuple[str, ET.Element]]:
    for name in zip_file.namelist():
        if not name.endswith(".xml"):
            continue
        try:
            yield name, ET.fromstring(zip_file.read(name))
        except ET.ParseError:
            continue


def audit_docx(path: Path) -> Dict[str, Any]:
    findings: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {
        "archive_ok": False,
        "core_properties_checked": False,
        "custom_properties_checked": False,
        "comments_checked": False,
        "tracked_changes_checked": False,
        "rsid_checked": False,
        "visible_identifiers_checked": False,
    }
    try:
        with ZipFile(path) as zip_file:
            bad_member = zip_file.testzip()
            if bad_member:
                findings.append(f"corrupt DOCX archive member: {bad_member}")
                return {
                    "findings": findings,
                    "warnings": warnings,
                    "checks": checks,
                }
            checks["archive_ok"] = True
            names = set(zip_file.namelist())

            if "docProps/core.xml" in names:
                root = ET.fromstring(zip_file.read("docProps/core.xml"))
                for element in root:
                    name = local_name(element.tag)
                    if name in DOCX_CORE_SENSITIVE and nonempty(element.text):
                        findings.append(f"non-empty DOCX core property {name!r}")
            checks["core_properties_checked"] = True

            if "docProps/custom.xml" in names:
                root = ET.fromstring(zip_file.read("docProps/custom.xml"))
                for prop in root:
                    prop_name = prop.attrib.get("name", "unnamed")
                    if any(nonempty(child.text) for child in prop):
                        findings.append(f"non-empty DOCX custom property {prop_name!r}")
            checks["custom_properties_checked"] = True

            if "word/comments.xml" in names:
                root = ET.fromstring(zip_file.read("word/comments.xml"))
                comments = [
                    element
                    for element in root.iter()
                    if local_name(element.tag) == "comment"
                ]
                if comments:
                    findings.append(f"DOCX contains {len(comments)} comment(s)")
            checks["comments_checked"] = True

            text_parts: List[str] = []
            tracked_count = 0
            rsid_count = 0
            for name, root in iter_docx_xml(zip_file):
                if name.startswith("word/"):
                    text_parts.extend(
                        element.text or ""
                        for element in root.iter()
                        if local_name(element.tag) == "t"
                    )
                for element in root.iter():
                    if local_name(element.tag) in TRACKED_CHANGE_TAGS:
                        tracked_count += 1
                    rsid_count += sum(
                        1 for attribute in element.attrib if local_name(attribute).startswith("rsid")
                    )
            if tracked_count:
                findings.append(f"DOCX contains {tracked_count} tracked-change marker(s)")
            if rsid_count:
                findings.append(f"DOCX contains {rsid_count} rsid attribute(s)")
            checks["tracked_changes_checked"] = True
            checks["rsid_checked"] = True
            findings.extend(visible_identifier_findings("\n".join(text_parts)))
            checks["visible_identifiers_checked"] = True
    except BadZipFile:
        findings.append("file is not a valid DOCX ZIP archive")
    except Exception as exc:
        findings.append(f"DOCX audit failed: {exc}")
    return {"findings": findings, "warnings": warnings, "checks": checks}


def audit_pdf(path: Path) -> Dict[str, Any]:
    findings: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {
        "pdf_readable": False,
        "metadata_checked": False,
        "xmp_checked": False,
        "visible_identifiers_checked": False,
    }
    try:
        from pypdf import PdfReader
    except ImportError:
        findings.append("pypdf is required to prove PDF anonymity")
        return {"findings": findings, "warnings": warnings, "checks": checks}

    try:
        reader = PdfReader(path)
        checks["pdf_readable"] = True
        metadata = dict(reader.metadata or {})
        for key, value in metadata.items():
            if not nonempty(value):
                continue
            if key in PDF_ALWAYS_SENSITIVE:
                findings.append(f"non-empty PDF metadata {key}")
            elif key in {"/Creator", "/Producer"}:
                if not GENERIC_PDF_APP_RE.search(str(value)):
                    findings.append(f"identity-like PDF metadata {key}")
            elif key not in PDF_ALLOWED_KEYS:
                findings.append(f"non-standard non-empty PDF metadata {key}")
        checks["metadata_checked"] = True

        try:
            xmp = reader.xmp_metadata
            if xmp is not None:
                for field in (
                    "dc_creator",
                    "dc_title",
                    "dc_subject",
                    "dc_description",
                    "pdf_keywords",
                ):
                    value = getattr(xmp, field, None)
                    if nonempty(value):
                        findings.append(f"non-empty PDF XMP field {field}")
            checks["xmp_checked"] = True
        except Exception as exc:
            warnings.append(f"PDF XMP could not be inspected: {exc}")

        extracted: List[str] = []
        extraction_failures = 0
        for page in reader.pages:
            try:
                extracted.append(page.extract_text() or "")
            except Exception:
                extraction_failures += 1
        if extraction_failures:
            warnings.append(
                f"visible-text extraction failed on {extraction_failures}/{len(reader.pages)} page(s)"
            )
        else:
            checks["visible_identifiers_checked"] = True
        findings.extend(visible_identifier_findings("\n".join(extracted)))
    except Exception as exc:
        findings.append(f"PDF audit failed: {exc}")
    return {"findings": findings, "warnings": warnings, "checks": checks}


def audit_file(path: Path) -> Dict[str, Any]:
    path = path.resolve()
    result: Dict[str, Any] = {
        "schema_version": "1.0",
        "path": str(path),
        "format": path.suffix.lower().lstrip("."),
        "sha256": None,
        "status": "fail",
        "findings": [],
        "warnings": [],
        "checks": {},
    }
    if not path.is_file():
        result["findings"] = ["file does not exist"]
        return result
    result["sha256"] = sha256_file(path)
    if AWARD_LABEL_RE.search(path.name):
        result["findings"].append("filename leaks an award/exemplar label")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        detail = audit_docx(path)
    elif suffix == ".pdf":
        detail = audit_pdf(path)
    else:
        result["findings"].append(f"unsupported blind-paper format: {suffix or '(none)'}")
        return result
    result["findings"].extend(detail["findings"])
    result["warnings"].extend(detail["warnings"])
    result["checks"] = detail["checks"]
    result["status"] = "pass" if not result["findings"] else "fail"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_file(args.file)
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
