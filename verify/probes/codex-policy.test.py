#!/usr/bin/env python3
"""Verify Codex policy defaults, migration, and user overrides."""

import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGURER = ROOT / "bin/configure-codex.py"


class CodexPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / ".codex/config.toml"

    def configure(self) -> None:
        subprocess.run(
            ["python3", str(CONFIGURER), str(self.config)],
            check=True,
            capture_output=True,
            text=True,
        )

    def read(self) -> dict[str, object]:
        return tomllib.loads(self.config.read_text())

    def test_defaults_enable_the_native_workspace_sandbox(self) -> None:
        self.configure()
        config = self.read()
        self.assertEqual(config["approval_policy"], "on-request")
        self.assertEqual(config["sandbox_mode"], "workspace-write")
        self.assertEqual(config["model"], "gpt-5.6-luna")

    def test_old_policy_pair_migrates_and_keeps_other_content(self) -> None:
        self.config.parent.mkdir(parents=True)
        self.config.write_text(
            'approval_policy = "never" # previous default\n'
            'sandbox_mode = "danger-full-access"\n'
            '\n[tui]\nnotifications = false\n'
        )

        self.configure()

        config = self.read()
        self.assertEqual(config["approval_policy"], "on-request")
        self.assertEqual(config["sandbox_mode"], "workspace-write")
        self.assertEqual(config["tui"]["notifications"], False)
        self.assertIn("# previous default", self.config.read_text())

    def test_manual_values_are_preserved(self) -> None:
        self.config.parent.mkdir(parents=True)
        self.config.write_text(
            'approval_policy = "never"\n'
            'sandbox_mode = "read-only"\n'
            'model = "user-model"\n'
        )

        self.configure()

        config = self.read()
        self.assertEqual(config["approval_policy"], "never")
        self.assertEqual(config["sandbox_mode"], "read-only")
        self.assertEqual(config["model"], "user-model")

    def test_migration_is_idempotent(self) -> None:
        self.config.parent.mkdir(parents=True)
        self.config.write_text(
            'approval_policy = "never"\n'
            'sandbox_mode = "danger-full-access"\n'
        )
        self.configure()
        first = self.config.read_bytes()
        self.configure()
        self.assertEqual(self.config.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
