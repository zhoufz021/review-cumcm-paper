from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "review-cumcm-paper"


def load_build_release_module():
    path = ROOT / "tools/build_release.py"
    spec = importlib.util.spec_from_file_location("review_build_release", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load tools/build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryRegressionTests(unittest.TestCase):
    def test_generated_python_cache_does_not_block_validation_or_packaging(self) -> None:
        cache_dir = SKILL / "scripts/__pycache__"
        cache_file = cache_dir / "synthetic-release-check.pyc"
        cache_dir_preexisted = cache_dir.exists()
        cache_dir.mkdir(exist_ok=True)
        cache_file.write_bytes(b"synthetic cache fixture")
        try:
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONUTF8"] = "1"
            validation = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/validate_repository.py"),
                    "--skip-cli-help",
                ],
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
            self.assertEqual(validation.returncode, 0, validation.stdout)

            build_release = load_build_release_module()
            archive_bytes = build_release.archive_bytes()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                names = archive.namelist()
            self.assertFalse(any("__pycache__" in name for name in names))
            self.assertFalse(any(name.endswith((".pyc", ".pyo")) for name in names))
        finally:
            cache_file.unlink(missing_ok=True)
            if not cache_dir_preexisted and cache_dir.exists() and not any(cache_dir.iterdir()):
                cache_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
