#!/usr/bin/env python3
"""Extract location-preserving text from PDF, DOCX, Markdown, or plain text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from xml.etree import ElementTree as ET


HEADING_RE = re.compile(
    r"^\s*(?:摘要|关键词|参考文献|附录|"
    r"[一二三四五六七八九十]+[、.．]\s*\S+|"
    r"\d+(?:\.\d+){1,3}\s*\S+|"
    r"\d+[、.．]\s*\S+|"
    r"(?:[1-9]|1[0-2])\s+[\u3400-\u9fff]{2,}|"
    r"(?:问题|模型|结果|结论|检验|验证|误差|敏感性)\s*[一二三四五六七八九十0-9]*)\s*$"
)
FIGURE_RE = re.compile(r"(?:图|Figure|Fig\.?)\s*[A-Za-z0-9一二三四五六七八九十.\-]+", re.I)
TABLE_RE = re.compile(r"(?:表|Table)\s*[A-Za-z0-9一二三四五六七八九十.\-]+", re.I)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def collect_markers(lines: Iterable[str]) -> Dict[str, List[str]]:
    headings: List[str] = []
    figures: List[str] = []
    tables: List[str] = []
    for line in lines:
        if len(line) <= 80 and HEADING_RE.match(line):
            headings.append(line)
        figures.extend(FIGURE_RE.findall(line))
        tables.extend(TABLE_RE.findall(line))
    return {
        "headings": list(dict.fromkeys(headings)),
        "figure_mentions": list(dict.fromkeys(figures)),
        "table_mentions": list(dict.fromkeys(tables)),
    }


def extract_pdf(path: Path) -> Dict[str, Any]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires pdfplumber") from exc

    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            text = clean_text(raw)
            char_count = len(text)
            cjk_count = len(CJK_RE.findall(text))
            markers = collect_markers(text.splitlines())
            sparse = char_count < 200 or cjk_count < 40
            pages.append(
                {
                    "file_page": index,
                    "location": f"PDF file page {index}",
                    "char_count": char_count,
                    "cjk_count": cjk_count,
                    "text_status": "sparse" if sparse else "usable",
                    "text": text,
                    **markers,
                }
            )

    sparse_pages = [page["file_page"] for page in pages if page["text_status"] == "sparse"]
    total_chars = sum(page["char_count"] for page in pages)
    overall = "sparse_text" if pages and len(sparse_pages) / len(pages) > 0.35 else "full_text"
    warnings: List[str] = []
    if overall == "sparse_text":
        warnings.append(
            "The PDF text layer is sparse on more than 35% of pages. Render or OCR relevant pages "
            "before treating text-search misses as missing content."
        )
    return {
        "format": "pdf",
        "location_basis": "file_page_1_based",
        "extraction_status": overall,
        "page_count": len(pages),
        "total_chars": total_chars,
        "sparse_pages": sparse_pages,
        "warnings": warnings,
        "pages": pages,
    }


def paragraph_style(paragraph: ET.Element) -> Optional[str]:
    properties = paragraph.find(f"{W_NS}pPr")
    if properties is None:
        return None
    style = properties.find(f"{W_NS}pStyle")
    if style is None:
        return None
    return style.attrib.get(f"{W_NS}val")


def extract_docx(path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        try:
            xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise RuntimeError("DOCX is missing word/document.xml") from exc

    root = ET.fromstring(xml)
    paragraphs: List[Dict[str, Any]] = []
    for node in root.iter(f"{W_NS}p"):
        text = clean_text("".join(item.text or "" for item in node.iter(f"{W_NS}t")))
        if not text:
            continue
        number = len(paragraphs) + 1
        markers = collect_markers([text])
        paragraphs.append(
            {
                "paragraph": number,
                "location": f"DOCX paragraph {number}",
                "style": paragraph_style(node),
                "text": text,
                **markers,
            }
        )

    return {
        "format": "docx",
        "location_basis": "paragraph_1_based_no_stable_pages",
        "extraction_status": "paragraph_text",
        "paragraph_count": len(paragraphs),
        "total_chars": sum(len(item["text"]) for item in paragraphs),
        "warnings": [
            "DOCX pagination is not stable in this extraction. Cite heading paths and paragraph/table "
            "locations; do not invent PDF page numbers."
        ],
        "paragraphs": paragraphs,
    }


def extract_text_file(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    lines = [clean_text(line) for line in raw.splitlines()]
    records = []
    for index, text in enumerate(lines, start=1):
        if not text:
            continue
        records.append(
            {
                "line": index,
                "location": f"text line {index}",
                "text": text,
                **collect_markers([text]),
            }
        )
    return {
        "format": path.suffix.lower().lstrip("."),
        "location_basis": "line_1_based",
        "extraction_status": "line_text",
        "line_count": len(lines),
        "total_chars": sum(len(item["text"]) for item in records),
        "warnings": [],
        "lines": records,
    }


def extract(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        payload = extract_pdf(path)
    elif suffix == ".docx":
        payload = extract_docx(path)
    elif suffix in {".txt", ".md"}:
        payload = extract_text_file(path)
    elif suffix == ".doc":
        raise RuntimeError(
            "Legacy .doc is not supported. Convert it to PDF or DOCX, or mark the material unreadable."
        )
    else:
        raise RuntimeError(f"Unsupported input format: {suffix or '<none>'}")

    return {
        "schema_version": "1.0",
        "source": {
            "path": str(path.resolve()),
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        },
        **payload,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Input PDF, DOCX, MD, or TXT")
    parser.add_argument("--output", type=Path, help="Output UTF-8 JSON; stdout when omitted")
    parser.add_argument("--compact", action="store_true", help="Write compact JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2
    try:
        payload = extract(args.input)
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
