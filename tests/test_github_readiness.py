"""Pruebas de readiness antes de publicar en GitHub privado."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from github_readiness import check_github_readiness, readiness_payload, write_json_output


class GitHubReadinessTests(unittest.TestCase):
    def test_readiness_passes_when_git_identity_commit_remote_and_candidates_are_safe(self) -> None:
        outputs = {
            ("git", "rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("git", "branch", "--show-current"): (0, "main"),
            ("git", "config", "--get", "user.name"): (0, "Joan"),
            ("git", "config", "--get", "user.email"): (0, "joan@example.com"),
            ("git", "log", "--oneline", "-1"): (0, "abc123 Initial"),
            ("git", "remote", "-v"): (0, "origin https://github.com/x/y.git"),
        }

        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            code, stdout = outputs[command]
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        items = check_github_readiness(runner=runner, candidates=["app.py"])

        self.assertTrue(all(item.passed for item in items))
        self.assertTrue(all(item.action == "" for item in items))
        self.assertEqual(items[-1].detail, "1 candidatos revisados sin bloqueos.")

    def test_readiness_marks_missing_publish_setup_as_pending(self) -> None:
        outputs = {
            ("git", "rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("git", "branch", "--show-current"): (0, "master"),
            ("git", "config", "--get", "user.name"): (1, ""),
            ("git", "config", "--get", "user.email"): (1, ""),
            ("git", "log", "--oneline", "-1"): (1, "fatal: no commits"),
            ("git", "remote", "-v"): (0, ""),
        }

        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            code, stdout = outputs[command]
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        items = check_github_readiness(runner=runner, candidates=[".env"])
        statuses = {item.name: item.status for item in items}

        self.assertEqual(statuses["git_repo"], "OK")
        self.assertEqual(statuses["git_branch"], "PENDIENTE")
        self.assertEqual(statuses["git_user_name"], "PENDIENTE")
        self.assertEqual(statuses["git_user_email"], "PENDIENTE")
        self.assertEqual(statuses["initial_commit"], "PENDIENTE")
        self.assertEqual(statuses["git_remote"], "PENDIENTE")
        self.assertEqual(statuses["prepublish_candidates"], "BLOQUEADO")
        actions = {item.name: item.action for item in items}
        self.assertEqual(actions["git_user_name"], 'git config user.name "TU NOMBRE"')
        self.assertEqual(actions["git_user_email"], 'git config user.email "TU EMAIL"')
        self.assertEqual(actions["git_branch"], "git branch -M main")
        self.assertIn("git commit", actions["initial_commit"])
        self.assertIn("git remote add origin", actions["git_remote"])
        self.assertIn("prepublish_check.py --manifest", actions["prepublish_candidates"])

    def test_readiness_payload_is_serializable_and_counts_pending_items(self) -> None:
        outputs = {
            ("git", "rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("git", "branch", "--show-current"): (0, "main"),
            ("git", "config", "--get", "user.name"): (1, ""),
            ("git", "config", "--get", "user.email"): (0, "joan@example.com"),
            ("git", "log", "--oneline", "-1"): (1, "fatal: no commits"),
            ("git", "remote", "-v"): (0, ""),
        }

        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            code, stdout = outputs[command]
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        payload = readiness_payload(
            check_github_readiness(runner=runner, candidates=["app.py"])
        )

        self.assertEqual(payload["status"], "PENDIENTE")
        self.assertEqual(payload["pending_count"], 3)
        self.assertEqual(payload["items"][0]["name"], "git_repo")
        self.assertIn("action", payload["items"][1])

    def test_readiness_payload_is_blocked_when_candidates_are_unsafe(self) -> None:
        outputs = {
            ("git", "rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("git", "branch", "--show-current"): (0, "main"),
            ("git", "config", "--get", "user.name"): (0, "Joan"),
            ("git", "config", "--get", "user.email"): (0, "joan@example.com"),
            ("git", "log", "--oneline", "-1"): (0, "abc123 Initial"),
            ("git", "remote", "-v"): (0, "origin https://github.com/x/y.git"),
        }

        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            code, stdout = outputs[command]
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        payload = readiness_payload(
            check_github_readiness(runner=runner, candidates=["nested/.env.local"])
        )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertEqual(payload["pending_count"], 1)

    def test_write_json_output_creates_parent_directory(self) -> None:
        payload = {"status": "PENDIENTE", "pending_count": 1}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "readiness.json"
            write_json_output(output, payload)
            loaded = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
