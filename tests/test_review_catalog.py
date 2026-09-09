"""Pruebas del catálogo oficial de revisiones manuales."""

import re
from pathlib import Path
import unittest

from review_catalog import MANUAL_REVIEW_CATALOG, format_review_catalog


class ReviewCatalogTests(unittest.TestCase):
    def test_pipeline_review_keys_are_registered(self) -> None:
        pipeline_path = Path(__file__).resolve().parents[1] / "analysis_pipeline.py"
        source = pipeline_path.read_text(encoding="utf-8")
        keys = set(re.findall(r'context\.review\("([^"]+)"\)', source))

        self.assertTrue(keys)
        self.assertTrue(keys.issubset(MANUAL_REVIEW_CATALOG))

    def test_catalog_contains_human_readable_metadata(self) -> None:
        for key, definition in MANUAL_REVIEW_CATALOG.items():
            self.assertEqual(key, definition.key)
            self.assertTrue(definition.label)
            self.assertTrue(definition.group)
            self.assertTrue(definition.source.startswith("docs/"))

    def test_markdown_catalog_lists_keys(self) -> None:
        markdown = format_review_catalog()

        self.assertIn("| Clave | Grupo | Revisión | Fuente |", markdown)
        self.assertIn("`ct15.prior_trend`", markdown)
        self.assertIn("`magnet.worden_volume_cross`", markdown)

    def test_documented_catalog_matches_generated_catalog(self) -> None:
        catalog_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "MANUAL_REVIEW_CATALOG.md"
        )

        self.assertEqual(
            catalog_path.read_text(encoding="utf-8").strip(),
            format_review_catalog().strip(),
        )


if __name__ == "__main__":
    unittest.main()
