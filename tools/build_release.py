#!/usr/bin/env python3
"""Build a deterministic review-cumcm-paper release archive and checksum."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "review-cumcm-paper"
DIST = ROOT / "dist"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
FIXED_TIME = (2026, 8, 1, 0, 0, 0)


def is_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def archive_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(SKILL.rglob("*")):
            if not path.is_file():
                continue
            if is_cache_file(path):
                continue
            relative = path.relative_to(SKILL).as_posix()
            info = zipfile.ZipInfo(f"review-cumcm-paper/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if path.suffix == ".py" else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Semantic version, for example 1.0.0")
    args = parser.parse_args()
    if not VERSION_PATTERN.fullmatch(args.version):
        parser.error("--version must be a semantic version such as 1.0.0")

    validation = subprocess.run(
        [sys.executable, str(ROOT / "tools/validate_repository.py")],
        cwd=ROOT,
        check=False,
    )
    if validation.returncode != 0:
        print("Repository validation failed; release was not built.", file=sys.stderr)
        return validation.returncode

    first = archive_bytes()
    second = archive_bytes()
    if first != second:
        print("Deterministic build verification failed.", file=sys.stderr)
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    archive_name = f"review-cumcm-paper-v{args.version}.zip"
    archive_path = DIST / archive_name
    archive_path.write_bytes(first)
    digest = hashlib.sha256(first).hexdigest()
    checksum_path = DIST / "SHA256SUMS.txt"
    with checksum_path.open("w", encoding="utf-8", newline="\n") as checksum_file:
        checksum_file.write(f"{digest}  {archive_name}\n")

    with zipfile.ZipFile(archive_path) as archive:
        file_entries = [name for name in archive.namelist() if not name.endswith("/")]
    expected_entries = [
        f"review-cumcm-paper/{path.relative_to(SKILL).as_posix()}"
        for path in sorted(SKILL.rglob("*"))
        if path.is_file() and not is_cache_file(path)
    ]
    if file_entries != expected_entries:
        print("Release archive entries do not match the validated Skill.", file=sys.stderr)
        return 1

    print(f"Built: {archive_path}")
    print(f"SHA-256: {digest}")
    print(f"Files: {len(file_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
