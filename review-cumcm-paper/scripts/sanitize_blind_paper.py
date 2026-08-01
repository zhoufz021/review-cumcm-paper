#!/usr/bin/env python3
"""Create a metadata-scrubbed DOCX or PDF copy for blind review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from audit_anonymity import DOCX_CORE_SENSITIVE, audit_file, local_name


CUSTOM_REL_SUFFIX = "/custom-properties"
CUSTOM_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.custom-properties+xml"
)
RSID_ATTRIBUTE_RE = re.compile(
    rb"\s+[A-Za-z_][A-Za-z0-9_.-]*:rsid[A-Za-z0-9_.-]*=\"[^\"]*\""
)
CORE_NAMESPACES = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def docx_body_text(zip_file: ZipFile) -> str:
    root = ET.fromstring(zip_file.read("word/document.xml"))
    return "".join(
        element.text or "" for element in root.iter() if local_name(element.tag) == "t"
    )


def scrub_xml(name: str, data: bytes) -> bytes:
    # Removing rsid attributes byte-for-byte avoids reserializing arbitrary Word
    # XML.  Word parts often contain prefix names inside attribute *values*
    # (for example mc:Ignorable); ElementTree may rename or drop those prefix
    # declarations and leave a ZIP-valid but Office-unreadable document.
    scrubbed = RSID_ATTRIBUTE_RE.sub(b"", data)
    if name not in {
        "docProps/core.xml",
        "_rels/.rels",
        "[Content_Types].xml",
    }:
        return scrubbed

    root = ET.fromstring(scrubbed)
    changed = scrubbed != data
    if name == "docProps/core.xml":
        for prefix, namespace in CORE_NAMESPACES.items():
            ET.register_namespace(prefix, namespace)
        for element in root:
            if local_name(element.tag) in DOCX_CORE_SENSITIVE and element.text:
                element.text = None
                changed = True
    if name == "_rels/.rels":
        for relationship in list(root):
            if relationship.attrib.get("Type", "").endswith(CUSTOM_REL_SUFFIX):
                root.remove(relationship)
                changed = True
    if name == "[Content_Types].xml":
        for override in list(root):
            if override.attrib.get("ContentType") == CUSTOM_CONTENT_TYPE:
                root.remove(override)
                changed = True
    if not changed:
        return scrubbed
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sanitize_docx(source: Path, output: Path) -> Dict[str, Any]:
    with ZipFile(source) as before:
        before_text_hash = text_hash(docx_body_text(before))
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as after:
            for info in before.infolist():
                if info.filename == "docProps/custom.xml":
                    continue
                data = before.read(info.filename)
                if info.filename.endswith(".xml") or info.filename == "_rels/.rels":
                    try:
                        data = scrub_xml(info.filename, data)
                    except ET.ParseError:
                        pass
                after.writestr(info, data)
    with ZipFile(output) as after:
        bad_member = after.testzip()
        after_text_hash = text_hash(docx_body_text(after))
    return {
        "archive_ok": bad_member is None,
        "body_text_hash_unchanged": before_text_hash == after_text_hash,
    }


def pdf_text_digest(reader: Any) -> str:
    return text_hash("\n".join((page.extract_text() or "") for page in reader.pages))


def sanitize_pdf(source: Path, output: Path) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("pypdf is required to sanitize PDF metadata") from exc

    before = PdfReader(source)
    before_pages = len(before.pages)
    before_text_hash = pdf_text_digest(before)
    before_boxes = [tuple(float(value) for value in page.mediabox) for page in before.pages]

    writer = PdfWriter(clone_from=before)
    writer.metadata = None
    if "/Metadata" in writer.root_object:
        del writer.root_object["/Metadata"]
    with output.open("wb") as handle:
        writer.write(handle)

    after = PdfReader(output)
    after_pages = len(after.pages)
    after_text_hash = pdf_text_digest(after)
    after_boxes = [tuple(float(value) for value in page.mediabox) for page in after.pages]
    return {
        "page_count_before": before_pages,
        "page_count_after": after_pages,
        "page_count_unchanged": before_pages == after_pages,
        "page_boxes_unchanged": before_boxes == after_boxes,
        "text_hash_unchanged": before_text_hash == after_text_hash,
    }


def sanitize(source: Path, output: Path) -> Dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("Input and output must be different paths.")
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() != output.suffix.lower():
        raise ValueError("Input and output extensions must match.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.stem}-",
        suffix=output.suffix,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        if source.suffix.lower() == ".docx":
            content_checks = sanitize_docx(source, temporary_path)
        elif source.suffix.lower() == ".pdf":
            content_checks = sanitize_pdf(source, temporary_path)
        else:
            raise ValueError("Only DOCX and PDF blind papers are supported.")
        failed_content_checks = [
            key
            for key, value in content_checks.items()
            if (key == "archive_ok" or key.endswith("_unchanged")) and value is not True
        ]
        if failed_content_checks:
            raise RuntimeError(
                "Sanitization changed or damaged paper content: "
                + ", ".join(failed_content_checks)
            )
        audit = audit_file(temporary_path)
        if audit["status"] != "pass":
            raise RuntimeError(
                "Sanitized copy still fails anonymity audit: "
                + "; ".join(audit["findings"])
            )
        temporary_path.replace(output)
        audit["path"] = str(output)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {
        "schema_version": "1.0",
        "source": str(source),
        "output": str(output),
        "status": "pass",
        "content_checks": content_checks,
        "anonymity_audit": audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = sanitize(args.input, args.output)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "source": str(args.input),
            "output": str(args.output),
            "status": "fail",
            "error": str(exc),
        }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
