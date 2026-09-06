#!/usr/bin/env python3
"""Deterministic tests for the toolkit platform adapters.

Every test supplies its own machine facts, so the result never depends on the
machine the suite runs on.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "toolkit-install"
loader = SourceFileLoader("toolkit_install", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec
toolkit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toolkit
loader.exec_module(toolkit)

CAPABILITIES = ROOT / "manifests" / "capabilities.json"
PLATFORMS = ROOT / "manifests" / "platforms.json"


def adapter(identifier, **overrides):
    document = {
        "id": identifier,
        "name": identifier,
        "family": identifier,
        "support": "experimental",
        "note": "a platform",
        "detect": {"kind": "os-release", "ids": [identifier]},
        "provides": {},
        "hints": {},
    }
    document.update(overrides)
    return document


def adapters(*documents):
    """Write a platform manifest into a throwaway file and load it."""
    path = Path(tempfile.mkdtemp()) / "platforms.json"
    path.write_text(
        json.dumps({"version": 1, "platforms": list(documents)}), encoding="utf-8"
    )
    return toolkit.load_adapters(path)


def host(commands=(), executables=(), system="Linux", in_container=False,
         os_release=None, wsl=False):
    return toolkit.Host(
        which=lambda name: f"/usr/bin/{name}" if name in commands else None,
        is_executable=lambda path: path in executables,
        system=system,
        machine="x86_64",
        in_container=in_container,
        os_release=os_release or {},
        wsl=wsl,
    )


# ------------------------------------------------------------- the manifest --


class ManifestCase(unittest.TestCase):
    def test_an_adapter_round_trips(self):
        loaded = adapters(adapter("alpha", support="verified"))
        self.assertEqual(loaded[0].id, "alpha")
        self.assertEqual(loaded[0].support, "verified")

    def test_version_must_be_one(self):
        path = Path(tempfile.mkdtemp()) / "platforms.json"
        path.write_text(json.dumps({"version": 2, "platforms": []}), encoding="utf-8")
        with self.assertRaisesRegex(toolkit.ConfigError, "version must be 1"):
            toolkit.load_adapters(path)

    def test_support_must_be_a_known_tier(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "support must be one of"):
            adapters(adapter("alpha", support="pretty good"))

    def test_a_duplicate_platform_id_is_refused(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "duplicate platform id"):
            adapters(adapter("alpha"), adapter("alpha"))

    def test_a_detect_rule_must_be_known(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "detect.kind"):
            adapters(adapter("alpha", detect={"kind": "vibes"}))

    def test_an_os_release_rule_must_name_something(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "at least one os-release id"):
            adapters(adapter("alpha", detect={"kind": "os-release"}))

    def test_an_empty_hint_is_refused(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "hints"):
            adapters(adapter("alpha", hints={"git": "   "}))

    def test_an_adapter_may_not_answer_with_a_platform_probe(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "must not be platform"):
            adapters(adapter("alpha", provides={"git": {"kind": "platform"}}))

    def test_an_adapter_may_only_name_a_declared_capability(self):
        capabilities = toolkit.load_capabilities(CAPABILITIES)
        loaded = adapters(adapter("alpha", hints={"quantum": "buy a laboratory"}))
        with self.assertRaisesRegex(toolkit.ConfigError, "quantum"):
            toolkit.check_adapter_references(loaded, capabilities)

    def test_a_platform_only_capability_needs_a_provider(self):
        capabilities = toolkit.load_capabilities(CAPABILITIES)
        with self.assertRaisesRegex(toolkit.ConfigError, "platform-only"):
            toolkit.check_platform_capabilities(capabilities, adapters(adapter("alpha")))


# -------------------------------------------------------------- detection --


class DetectionCase(unittest.TestCase):
    def setUp(self):
        self.shipped = toolkit.load_adapters(PLATFORMS)

    def find(self, **facts):
        return toolkit.detect_platform(self.shipped, host(**facts))

    def test_the_primary_platform_is_detected_by_its_own_id(self):
        found = self.find(os_release={"ID": "bazzite", "ID_LIKE": "fedora"})
        self.assertEqual(found.id, "bazzite")
        self.assertEqual(found.support, "verified")

    def test_a_derivative_wins_over_the_family_it_derives_from(self):
        # Bazzite also reports ID_LIKE=fedora. Manifest order decides.
        self.assertEqual(
            self.find(os_release={"ID": "bazzite", "ID_LIKE": "fedora"}).id, "bazzite"
        )
        self.assertEqual(self.find(os_release={"ID": "fedora"}).id, "fedora")

    def test_an_unlisted_derivative_matches_on_the_family(self):
        found = self.find(os_release={"ID": "pop", "ID_LIKE": "ubuntu debian"})
        self.assertEqual(found.id, "debian")
        self.assertEqual(found.family, "debian")

    def test_uname_detects_a_platform_without_os_release(self):
        self.assertEqual(self.find(system="Darwin").id, "macos")

    def test_an_unknown_machine_matches_no_adapter(self):
        self.assertIsNone(self.find(os_release={"ID": "plan9"}))

    def test_os_release_is_parsed_without_quotes(self):
        path = Path(tempfile.mkdtemp()) / "os-release"
        path.write_text('ID="bazzite"\n# a comment\n\nID_LIKE=fedora\n', encoding="utf-8")
        fields = toolkit.read_os_release(path)
        self.assertEqual(fields["ID"], "bazzite")
        self.assertEqual(fields["ID_LIKE"], "fedora")

    def test_a_missing_os_release_is_not_an_error(self):
        self.assertEqual(toolkit.read_os_release(Path("/nonexistent/os-release")), {})


# ------------------------------------------------------------ capabilities --


class AdapterCapabilityCase(unittest.TestCase):
    def setUp(self):
        self.capabilities = toolkit.load_capabilities(CAPABILITIES)
        self.shipped = toolkit.load_adapters(PLATFORMS)

    def present(self, adapter_id, **facts):
        found = next(a for a in self.shipped if a.id == adapter_id)
        return toolkit.detect_capabilities(self.capabilities, host(**facts), found)

    def test_a_platform_only_capability_is_absent_without_an_adapter(self):
        present = toolkit.detect_capabilities(
            self.capabilities, host(commands={"dnf", "rpm-ostree"})
        )
        self.assertNotIn("package-manager", present)

    def test_the_adapter_supplies_the_package_manager(self):
        self.assertIn("package-manager", self.present("fedora", commands={"dnf"}))
        self.assertNotIn("package-manager", self.present("fedora", commands={"apt-get"}))
        self.assertIn("package-manager", self.present("debian", commands={"apt-get"}))

    def test_the_adapter_probe_replaces_the_generic_one(self):
        # Homebrew lives somewhere else on macOS. The generic probe misses it.
        facts = {"system": "Darwin", "executables": {"/opt/homebrew/bin/brew"}}
        self.assertNotIn(
            "homebrew", toolkit.detect_capabilities(self.capabilities, host(**facts))
        )
        self.assertIn("homebrew", self.present("macos", **facts))

    def test_a_generic_capability_is_unchanged_by_the_adapter(self):
        self.assertIn("git", self.present("fedora", commands={"git"}))
        self.assertNotIn("gh", self.present("fedora", commands={"git"}))

    def test_a_hint_is_the_step_for_this_platform(self):
        fedora = next(a for a in self.shipped if a.id == "fedora")
        debian = next(a for a in self.shipped if a.id == "debian")
        self.assertEqual(toolkit.capability_hint(fedora, "distrobox"),
                         "sudo dnf install distrobox")
        self.assertEqual(toolkit.capability_hint(debian, "distrobox"),
                         "sudo apt-get install distrobox")

    def test_an_unknown_platform_offers_no_hint(self):
        self.assertEqual(toolkit.capability_hint(None, "distrobox"), "")

    def test_every_shipped_adapter_is_consistent(self):
        toolkit.check_adapter_references(self.shipped, self.capabilities)
        toolkit.check_platform_capabilities(self.capabilities, self.shipped)
        self.assertEqual(
            [a.id for a in self.shipped if a.support == "verified"], ["bazzite"]
        )


# ------------------------------------------------------------------- plan --


class PlanCase(unittest.TestCase):
    def setUp(self):
        self.components = toolkit.load_components(ROOT / "components")
        self.shipped = toolkit.load_adapters(PLATFORMS)
        self.fedora = next(a for a in self.shipped if a.id == "fedora")

    def plan(self, selection, present, adapter=None, ready=()):
        reasons, order = toolkit.closure(self.components, selection)
        return toolkit.build_plan(
            self.components, reasons, order, frozenset(present), ROOT,
            doctor=lambda component, root: component.id in ready, adapter=adapter,
        )

    def test_a_blocked_component_carries_the_platform_step(self):
        plan = self.plan(["web-dev"], {"linux", "host"}, self.fedora)
        self.assertIn("sudo dnf install distrobox", plan.hints)
        self.assertTrue(plan.blocked)

    def test_an_unknown_platform_still_blocks_and_says_what_is_missing(self):
        plan = self.plan(["web-dev"], {"linux", "host"})
        self.assertEqual(plan.hints, ())
        self.assertIn("missing capability: distrobox",
                      toolkit.render_plan(plan))

    def test_a_supported_component_is_not_blocked_by_an_unsupported_one(self):
        # repo-labels needs neither Distrobox nor a container runtime, so a
        # machine without them still reports it as ready.
        plan = self.plan(
            ["repo-labels", "web-dev"], {"linux", "host", "python3"},
            self.fedora, ready=("repo-labels",),
        )
        blocked = [step.component.id for step in plan.blocked]
        self.assertIn("web-dev", blocked)
        self.assertNotIn("repo-labels", blocked)

    def test_the_hint_is_reported_once(self):
        plan = self.plan(["web-dev", "python-dev"], {"linux", "host"}, self.fedora)
        self.assertEqual(len(plan.hints), len(set(plan.hints)))

    def test_the_support_report_names_the_first_missing_capability(self):
        reasons = toolkit.unsupported(
            self.components, frozenset({"linux", "host", "python3"})
        )
        self.assertIn("distrobox", reasons["web-dev"])
        self.assertEqual(reasons["repo-labels"], "")

    def test_the_support_report_follows_the_dependency_chain(self):
        reasons = toolkit.unsupported(self.components, frozenset({"linux", "host"}))
        self.assertIn("blocked by", reasons["developer"])


# -------------------------------------------------------------------- CLI --


class CommandCase(unittest.TestCase):
    def run_installer(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_doctor_reports_the_platform_and_changes_nothing(self):
        result = self.run_installer("--doctor")
        self.assertEqual(result.returncode, toolkit.EXIT_OK)
        self.assertIn("Platform", result.stdout)
        self.assertIn("Capabilities", result.stdout)
        self.assertIn("Components", result.stdout)

    def test_doctor_reports_every_declared_capability(self):
        capabilities = toolkit.load_capabilities(CAPABILITIES)
        result = self.run_installer("--doctor")
        for identifier in capabilities:
            self.assertIn(identifier, result.stdout)

    def test_a_hint_is_printed_for_the_shell_half(self):
        result = self.run_installer("--hint", "homebrew")
        self.assertIn(result.returncode, (toolkit.EXIT_OK, toolkit.EXIT_CAPABILITY))
        if result.returncode == toolkit.EXIT_OK:
            self.assertTrue(result.stdout.strip())

    def test_an_unknown_capability_is_refused(self):
        result = self.run_installer("--hint", "quantum")
        self.assertEqual(result.returncode, toolkit.EXIT_USAGE)
        self.assertIn("unknown capability", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
