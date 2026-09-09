"""Pruebas del saneamiento comun de diagnosticos."""

import unittest

from safe_diagnostics import (
    sanitize_diagnostic_detail,
    sanitize_diagnostic_payload,
)


class SafeDiagnosticsTests(unittest.TestCase):
    def test_redacts_labeled_and_long_secrets(self) -> None:
        safe = sanitize_diagnostic_detail(
            "Authorization: Bearer-abcdefghijklmnopqrstuvwxyz "
            "token=short password=hunter2"
        )

        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", safe)
        self.assertNotIn("short", safe)
        self.assertNotIn("hunter2", safe)
        self.assertIn("[REDACTED]", safe)

    def test_redacts_sensitive_keys_recursively(self) -> None:
        safe = sanitize_diagnostic_payload(
            {
                "status": "ERROR",
                "api_key": "plain-key",
                "secrets_exposed": False,
                "nested": [{"Authorization": "Bearer value"}],
            }
        )

        self.assertEqual(safe["status"], "ERROR")
        self.assertEqual(safe["api_key"], "[REDACTED]")
        self.assertIs(safe["secrets_exposed"], False)
        self.assertEqual(safe["nested"][0]["Authorization"], "[REDACTED]")

    def test_rejects_nonpositive_limit(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_diagnostic_detail("error", limit=0)


if __name__ == "__main__":
    unittest.main()
