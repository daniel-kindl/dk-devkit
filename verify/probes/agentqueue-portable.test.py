#!/usr/bin/env python3
"""Build, install and smoke-test the portable agentq package."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
from agentqueue import runtime as runtime_mod  # noqa: E402


class PortablePackageTest(unittest.TestCase):
    def test_runner_is_resolved_from_path_when_not_bundled(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = pathlib.Path(temp)
            package_root = temp_path / "package"
            external_bin = temp_path / "external-bin"
            package_root.mkdir()
            external_bin.mkdir()
            agentbox = external_bin / "agentbox"
            agentbox.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            agentbox.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(external_bin)}):
                self.assertEqual(
                    runtime_mod.executable("agentbox", str(package_root), str(package_root)),
                    str(agentbox),
                )

    def test_runner_is_not_resolved_from_the_target_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = pathlib.Path(temp)
            package_root = temp_path / "package"
            repo_root = temp_path / "project"
            repo_bin = repo_root / "bin"
            repo_bin.mkdir(parents=True)
            package_root.mkdir()
            candidate = repo_bin / "agentbox"
            candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            candidate.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(repo_bin)}):
                self.assertEqual(
                    runtime_mod.executable("agentbox", str(package_root), str(repo_root)),
                    str(package_root / "bin/agentbox"),
                )

    def test_package_installs_without_the_devkit_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = pathlib.Path(temp)
            archive = temp_path / "agentq.tar.gz"
            build = subprocess.run(
                [str(ROOT / "tools/package-agentq"), str(archive)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            extracted = temp_path / "extracted"
            extracted.mkdir()
            with tarfile.open(archive, "r:gz") as package:
                package.extractall(extracted, filter="data")

            package_root = extracted / "agentq"
            required = (
                "bin/agentq",
                "bin/scan-secrets",
                "lib/agentqueue/cli.py",
                "config/agentqueue/policy.default.json",
                "manifests/model-tiers.json",
                "manifests/sandcastle.env",
                "manifests/github-labels.json",
                "install.sh",
            )
            for relative in required:
                self.assertTrue((package_root / relative).is_file(), relative)

            self.assertFalse((package_root / "bin/agentbox").exists())
            self.assertFalse((package_root / "bin/devbox").exists())
            smoke = subprocess.run(
                [str(package_root / "bin/agentq"), "--version"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(smoke.returncode, 0, smoke.stderr)
            self.assertRegex(smoke.stdout, r"^agentq \d+\.\d+\.\d+")

            prefix = temp_path / "prefix"
            env = dict(os.environ, PREFIX=str(prefix))
            install = subprocess.run(
                [str(package_root / "install.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            command = prefix / "bin/agentq"
            self.assertTrue(command.is_symlink())
            installed = subprocess.run(
                [str(command), "--version"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(installed.stdout.strip(), smoke.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
