"""Pruebas de consistencia del registro central de estrategias."""

import unittest
from pathlib import Path

from strategy_categories import StrategyCategory
from strategy_registry import STRATEGY_REGISTRY


class StrategyRegistryTests(unittest.TestCase):
    def test_registered_strategies_have_complete_metadata(self) -> None:
        self.assertGreaterEqual(len(STRATEGY_REGISTRY), 1)
        for strategy_id, metadata in STRATEGY_REGISTRY.items():
            self.assertEqual(strategy_id, strategy_id.upper())
            self.assertTrue(metadata["nombre"].strip())
            self.assertIsInstance(metadata["categoria"], StrategyCategory)
            self.assertTrue(metadata["sesgo"].strip())
            self.assertIsInstance(metadata["requiere_confirmacion"], bool)

    def test_registered_strategy_names_are_represented_in_master_index(self) -> None:
        index_path = Path(__file__).resolve().parents[1] / "docs" / "MASTER_STRATEGIES_INDEX.md"
        index_text = index_path.read_text(encoding="utf-8")

        missing = [
            metadata["nombre"]
            for metadata in STRATEGY_REGISTRY.values()
            if not any(part in index_text for part in metadata["nombre"].split())
        ]

        self.assertFalse(missing)

    def test_registered_strategies_are_documented_by_id_or_name(self) -> None:
        docs_root = Path(__file__).resolve().parents[1] / "docs"
        documentation = "\n".join(
            path.read_text(encoding="utf-8") for path in docs_root.rglob("*.md")
        )
        missing = [
            strategy_id
            for strategy_id, metadata in STRATEGY_REGISTRY.items()
            if strategy_id not in documentation and metadata["nombre"] not in documentation
        ]

        self.assertFalse(missing)


if __name__ == "__main__":
    unittest.main()
