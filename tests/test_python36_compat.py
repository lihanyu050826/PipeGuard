import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = list((ROOT / "pipeguard").glob("*.py")) + [ROOT / "run.py"]


class Python36CompatibilityTests(unittest.TestCase):
    def test_sources_parse_with_python36_grammar(self):
        if sys.version_info < (3, 8):
            self.skipTest("当前解释器会直接验证 Python 3.6 语法")
        for source_path in SOURCE_FILES:
            with self.subTest(source=source_path.name):
                source = source_path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(source_path), feature_version=(3, 6))

    def test_sources_do_not_import_newer_stdlib_helpers(self):
        forbidden = ("from __future__ import annotations", "dataclasses", "ThreadingHTTPServer")
        for source_path in SOURCE_FILES:
            with self.subTest(source=source_path.name):
                source = source_path.read_text(encoding="utf-8")
                for marker in forbidden:
                    self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()
