#!/usr/bin/env python3
"""Create a sanitized runtime copy of this skill with calibration conclusions removed."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


STUB = """# Blind runtime calibration stub

BLIND_RUNTIME_STUB

Calibration examples and candidate conclusions are intentionally unavailable in this runtime.
Complete the review from the original problem and paper before any post-test comparison.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    try:
        output.relative_to(source)
        print("Output must not be inside the source skill directory.", file=sys.stderr)
        return 2
    except ValueError:
        pass
    if output.exists():
        print(f"Output already exists; choose a new empty path: {output}", file=sys.stderr)
        return 2

    def ignore(directory: str, names: list) -> set:
        ignored = set()
        for name in names:
            if name == "__pycache__" or name.endswith((".pyc", ".pyo")):
                ignored.add(name)
        return ignored

    try:
        shutil.copytree(source, output, ignore=ignore)
        exemplar = output / "references/reviewed-exemplars.md"
        exemplar.write_text(STUB, encoding="utf-8")
    except Exception as exc:
        print(f"Blind runtime creation failed: {exc}", file=sys.stderr)
        return 2

    print(f"Created sanitized blind runtime at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
