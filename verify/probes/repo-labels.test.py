#!/usr/bin/env python3
"""Deterministic tests for the reusable repo-labels command."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "repo-labels"
MANIFEST = ROOT / "manifests" / "github-labels.json"
loader = SourceFileLoader("repo_labels", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec
repo_labels = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = repo_labels
loader.exec_module(repo_labels)


def label(name, color="123abc", description="desc", group=""):
    return repo_labels.Label(name, color, description, group)


class ManifestCase(unittest.TestCase):
    def write(self, document):
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        json.dump(document, tmp)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        return Path(tmp.name)

    def test_shipped_manifest_is_valid(self):
        labels = repo_labels.load_manifest(MANIFEST)
        names = {item.name for item in labels}
        self.assertIn("ready-for-agent", names)
        self.assertIn("agent-in-progress", names)
        self.assertIn("ready-for-human", names)
        self.assertIn("agent-failed", names)
        self.assertIn("wayfinder", names)

    def test_every_shipped_label_declares_a_known_group(self):
        # A group is documentation metadata, but agentq selects the lifecycle
        # labels by group. A typo there would silently empty that selection.
        known = {"type", "agent-workflow", "impact", "status"}
        for item in repo_labels.load_manifest(MANIFEST):
            self.assertIn(item.group, known, f"{item.name} has group {item.group!r}")

    def test_the_shipped_type_taxonomy_is_the_documented_one(self):
        types = {item.name for item in repo_labels.load_manifest(MANIFEST)
                 if item.group == "type"}
        self.assertEqual(types, {
            "bug", "feature", "enhancement", "refactor", "documentation",
            "security", "chore", "release", "research", "design",
            "verification", "performance", "dependencies", "platform-support",
        })

    def test_no_two_shipped_labels_share_a_color(self):
        # A badge is read by its color first. Two labels with one color are two
        # labels a reader cannot tell apart in an issue list.
        colors = {}
        for item in repo_labels.load_manifest(MANIFEST):
            colors.setdefault(item.color, []).append(item.name)
        shared = {color: names for color, names in colors.items() if len(names) > 1}
        self.assertEqual(shared, {}, f"labels share a color: {shared}")

    def test_the_impact_and_status_groups_hold_their_labels(self):
        labels = repo_labels.load_manifest(MANIFEST)
        by_group = {}
        for item in labels:
            by_group.setdefault(item.group, set()).add(item.name)
        self.assertEqual(by_group["impact"], {"breaking-change"})
        self.assertEqual(by_group["status"], {"blocked"})

    def test_the_documentation_describes_every_shipped_label(self):
        # docs/repo-labels.md prints the catalog as a table. A label the
        # manifest holds and the table omits is a catalog nobody can read; a
        # row the manifest does not hold is a label nobody can apply.
        document = (ROOT / "docs" / "repo-labels.md").read_text(encoding="utf-8")
        section = re.search(r"^## The canonical catalog$(.*?)^## ",
                            document, re.M | re.S)
        self.assertIsNotNone(section, "docs/repo-labels.md lost its catalog section")
        documented = dict(re.findall(r"^\| `([^`]+)` \| (.+?) \|$",
                                     section.group(1), re.M))
        shipped = {item.name: item.description
                   for item in repo_labels.load_manifest(MANIFEST)}
        self.assertEqual(documented, shipped)

    def test_duplicate_names_are_rejected_case_insensitively(self):
        path = self.write({"version": 1, "labels": [
            {"name": "Bug", "color": "ffffff", "description": "a"},
            {"name": "bug", "color": "000000", "description": "b"},
        ]})
        with self.assertRaises(repo_labels.ConfigError):
            repo_labels.load_manifest(path)

    def test_invalid_color_is_rejected(self):
        path = self.write({"version": 1, "labels": [
            {"name": "bug", "color": "red", "description": "a"},
        ]})
        with self.assertRaises(repo_labels.ConfigError):
            repo_labels.load_manifest(path)

    def test_description_limit_is_checked(self):
        path = self.write({"version": 1, "labels": [
            {"name": "bug", "color": "ffffff", "description": "x" * 101},
        ]})
        with self.assertRaises(repo_labels.ConfigError):
            repo_labels.load_manifest(path)


class PlanningCase(unittest.TestCase):
    def test_exact_repository_is_a_noop(self):
        desired = (label("bug"), label("feature", "abcdef", "new"))
        plan = repo_labels.build_plan(desired, desired)
        self.assertTrue(plan.exact)
        self.assertEqual(plan.changes, ())

    def test_missing_label_is_created(self):
        plan = repo_labels.build_plan((label("bug"),), ())
        self.assertEqual([c.name for c in plan.creates], ["bug"])
        self.assertFalse(plan.updates)
        self.assertFalse(plan.deletes)

    def test_metadata_drift_is_updated(self):
        plan = repo_labels.build_plan(
            (label("bug", "ffffff", "wanted"),),
            (label("bug", "000000", "old"),),
        )
        self.assertEqual([c.name for c in plan.updates], ["bug"])

    def test_canonical_case_is_updated(self):
        plan = repo_labels.build_plan((label("Bug"),), (label("bug"),))
        self.assertEqual([c.name for c in plan.updates], ["Bug"])

    def test_extra_label_is_deleted(self):
        plan = repo_labels.build_plan((), (label("extra"),))
        self.assertEqual([c.name for c in plan.deletes], ["extra"])

    def test_plan_order_is_deterministic(self):
        desired = (label("z"), label("a"))
        current = (label("y"), label("x"))
        plan = repo_labels.build_plan(desired, current)
        self.assertEqual([c.name for c in plan.creates], ["a", "z"])
        self.assertEqual([c.name for c in plan.deletes], ["x", "y"])

    def test_render_orders_create_update_delete(self):
        desired = (label("create"), label("same", "ffffff"))
        current = (label("same", "000000"), label("delete"))
        lines = repo_labels.render_plan(repo_labels.build_plan(desired, current)).splitlines()
        self.assertTrue(lines[0].startswith("CREATE"))
        self.assertTrue(lines[1].startswith("UPDATE"))
        self.assertTrue(lines[2].startswith("DELETE"))


class GitHubCase(unittest.TestCase):
    @mock.patch.object(repo_labels, "_run_gh")
    def test_explicit_repo_does_not_call_gh_for_resolution(self, run):
        self.assertEqual(repo_labels.resolve_repo("owner/name"), "owner/name")
        run.assert_not_called()

    @mock.patch.object(repo_labels, "_run_gh", return_value="owner/name\n")
    def test_current_repo_resolution_uses_gh(self, run):
        self.assertEqual(repo_labels.resolve_repo(None), "owner/name")
        self.assertEqual(run.call_args.args[0][:2], ["repo", "view"])

    @mock.patch.object(repo_labels, "_run_gh")
    def test_read_current_uses_only_label_metadata(self, run):
        run.return_value = json.dumps([
            {"name": "bug", "color": "D73A4A", "description": None},
        ])
        labels = repo_labels.read_current("owner/name")
        self.assertEqual(labels[0].color, "d73a4a")
        self.assertEqual(labels[0].description, "")
        argv = run.call_args.args[0]
        self.assertIn("--json", argv)
        self.assertNotIn("token", " ".join(argv).lower())

    @mock.patch.object(repo_labels, "_run_gh")
    def test_apply_creates_and_updates_before_deletes(self, run):
        desired = (label("new"), label("same", "ffffff", "wanted"))
        current = (label("same", "000000", "old"), label("obsolete"))
        repo_labels.apply_plan("owner/name", repo_labels.build_plan(desired, current))
        commands = [call.args[0][1] for call in run.call_args_list]
        self.assertEqual(commands, ["create", "edit", "delete"])


class SafetyCase(unittest.TestCase):
    def test_noninteractive_delete_requires_yes(self):
        plan = repo_labels.build_plan((), (label("obsolete"),))
        stdin = io.StringIO("")
        self.assertFalse(repo_labels._confirm_deletes(plan, False, stdin))
        self.assertTrue(repo_labels._confirm_deletes(plan, True, stdin))

    @mock.patch.object(repo_labels, "read_current")
    @mock.patch.object(repo_labels, "resolve_repo", return_value="owner/name")
    @mock.patch.object(repo_labels, "load_manifest")
    def test_check_returns_drift_without_mutation(self, manifest, _resolve, current):
        manifest.return_value = (label("bug"),)
        current.return_value = ()
        with mock.patch.object(repo_labels, "apply_plan") as apply:
            with mock.patch("sys.stdout", new=io.StringIO()):
                code = repo_labels.main(["check", "--repo", "owner/name"])
        self.assertEqual(code, repo_labels.EXIT_DRIFT)
        apply.assert_not_called()

    @mock.patch.object(repo_labels, "read_current")
    @mock.patch.object(repo_labels, "resolve_repo", return_value="owner/name")
    @mock.patch.object(repo_labels, "load_manifest")
    def test_dry_run_never_mutates(self, manifest, _resolve, current):
        manifest.return_value = (label("bug"),)
        current.return_value = (label("obsolete"),)
        with mock.patch.object(repo_labels, "apply_plan") as apply:
            with mock.patch("sys.stdout", new=io.StringIO()):
                code = repo_labels.main(["sync", "--repo", "owner/name", "--dry-run"])
        self.assertEqual(code, repo_labels.EXIT_OK)
        apply.assert_not_called()

    @mock.patch.object(repo_labels, "read_current")
    @mock.patch.object(repo_labels, "resolve_repo", return_value="owner/name")
    @mock.patch.object(repo_labels, "load_manifest")
    def test_noninteractive_sync_with_delete_refuses(self, manifest, _resolve, current):
        manifest.return_value = ()
        current.return_value = (label("obsolete"),)
        fake_stdin = io.StringIO("")
        with mock.patch.object(repo_labels, "apply_plan") as apply:
            with mock.patch("sys.stdin", fake_stdin), mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                code = repo_labels.main(["sync", "--repo", "owner/name"])
        self.assertEqual(code, repo_labels.EXIT_REFUSED)
        apply.assert_not_called()

    @mock.patch.object(repo_labels, "read_current")
    @mock.patch.object(repo_labels, "resolve_repo", return_value="owner/name")
    @mock.patch.object(repo_labels, "load_manifest")
    def test_yes_allows_destructive_sync_and_verifies(self, manifest, _resolve, current):
        manifest.return_value = ()
        current.side_effect = [(label("obsolete"),), ()]
        with mock.patch.object(repo_labels, "apply_plan") as apply:
            with mock.patch("sys.stdout", new=io.StringIO()):
                code = repo_labels.main(["sync", "--repo", "owner/name", "--yes"])
        self.assertEqual(code, repo_labels.EXIT_OK)
        apply.assert_called_once()
        self.assertEqual(current.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
