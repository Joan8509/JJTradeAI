"""Pruebas ligeras de calidad para documentacion versionable."""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [PROJECT_ROOT / "README.md", *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
ASCII_DOC_PATHS = [
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs" / "RELEASE_CHECKLIST.md",
    PROJECT_ROOT / "docs" / "USER_GUIDE.md",
    PROJECT_ROOT / "docs" / "VALIDATION_PROTOCOL.md",
]
MOJIBAKE_MARKERS = ("Ã", "â", "\ufffd")


class DocsTextQualityTests(unittest.TestCase):
    def test_docs_do_not_contain_common_mojibake_markers(self) -> None:
        offenders: list[str] = []
        for path in DOC_PATHS:
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in MOJIBAKE_MARKERS):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual(offenders, [])

    def test_primary_docs_are_ascii_stable(self) -> None:
        offenders: list[str] = []
        for path in ASCII_DOC_PATHS:
            text = path.read_text(encoding="utf-8")
            if not text.isascii():
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
