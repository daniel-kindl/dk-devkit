#!/usr/bin/env python3
"""Deterministic tests for the reusable repo-meta command."""

from __future__ import annotations

import dataclasses
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "repo-meta"
loader = SourceFileLoader("repo_meta", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec
repo_meta = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = repo_meta
loader.exec_module(repo_meta)


class WritesAManifest:
    """Write a throwaway manifest and remove it when the test ends."""

    def write(self, document):
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        json.dump(document, tmp)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        return Path(tmp.name)


class ManifestCase(WritesAManifest, unittest.TestCase):

    def test_shipped_manifest_is_valid(self):
        meta = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        self.assertTrue(meta.description)
        self.assertLessEqual(len(meta.description), repo_meta.DESCRIPTION_LIMIT)
        self.assertIn("developer-tools", meta.topics)
        self.assertEqual(list(meta.topics), sorted(meta.topics))

    def test_shipped_manifest_declares_the_toolkit_identity(self):
        # The description is the first thing a reader of the public repository
        # sees. It must name the product, not one machine.
        meta = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        self.assertIn("toolkit", meta.description.casefold())

    def test_version_must_be_one(self):
        path = self.write({"version": 2, "description": "a"})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_long_description_is_rejected(self):
        path = self.write({"version": 1, "description": "x" * 351})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_padded_description_is_rejected(self):
        path = self.write({"version": 1, "description": " padded "})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_multiline_description_is_rejected(self):
        path = self.write({"version": 1, "description": "one\ntwo"})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_homepage_must_be_a_url_or_empty(self):
        path = self.write({"version": 1, "homepage": "example.com"})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)
        self.assertEqual(
            repo_meta.load_manifest(self.write({"version": 1, "homepage": ""})).homepage,
            "",
        )

    def test_uppercase_topic_is_rejected(self):
        path = self.write({"version": 1, "topics": ["Linux"]})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_duplicate_topic_is_rejected(self):
        path = self.write({"version": 1, "topics": ["linux", "linux"]})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_too_many_topics_are_rejected(self):
        path = self.write({"version": 1, "topics": [f"t{n}" for n in range(21)]})
        with self.assertRaises(repo_meta.ConfigError):
            repo_meta.load_manifest(path)

    def test_topics_are_sorted_for_a_stable_plan(self):
        meta = repo_meta.load_manifest(
            self.write({"version": 1, "topics": ["zebra", "alpha"]})
        )
        self.assertEqual(meta.topics, ("alpha", "zebra"))


class SettingsManifestCase(WritesAManifest, unittest.TestCase):
    def settings(self, block):
        return repo_meta.load_manifest(
            self.write({"version": 1, "settings": block})
        ).settings

    def test_the_shipped_manifest_declares_every_managed_setting(self):
        # #17 asks for a deliberate answer on the default branch and the
        # repository settings. A setting the manifest omits is not managed, so
        # an omission here would be an answer nobody gave.
        meta = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        self.assertEqual(
            sorted(meta.settings), sorted(repo_meta.SETTING_KEYS)
        )

    def test_the_shipped_manifest_matches_the_audited_intent(self):
        # docs/public-release-audit.md records what the public repository
        # offers. These four values are that record.
        meta = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        self.assertEqual(meta.settings["default_branch"], "main")
        self.assertTrue(meta.settings["has_issues"])
        for surface in ("has_wiki", "has_projects", "has_discussions"):
            self.assertFalse(meta.settings[surface], surface)

    def test_an_absent_settings_block_manages_nothing(self):
        self.assertEqual(
            repo_meta.load_manifest(self.write({"version": 1})).settings, {}
        )

    def test_an_unmanaged_setting_is_rejected(self):
        with self.assertRaises(repo_meta.ConfigError):
            self.settings({"is_template": True})

    def test_a_setting_block_that_is_not_an_object_is_rejected(self):
        with self.assertRaises(repo_meta.ConfigError):
            self.settings(["has_wiki"])

    def test_a_non_boolean_toggle_is_rejected(self):
        # bool is a subclass of int, so 1 must not pass as true.
        for value in (1, 0, "true", None):
            with self.assertRaises(repo_meta.ConfigError):
                self.settings({"has_wiki": value})

    def test_an_invalid_branch_name_is_rejected(self):
        for name in ("", "-dash", "with space", "tab\tname"):
            with self.assertRaises(repo_meta.ConfigError):
                self.settings({"default_branch": name})

    def test_a_slashed_branch_name_is_accepted(self):
        self.assertEqual(
            self.settings({"default_branch": "release/1.x"})["default_branch"],
            "release/1.x",
        )

    def test_disabling_every_merge_method_is_rejected(self):
        with self.assertRaises(repo_meta.ConfigError):
            self.settings({
                "allow_merge_commit": False,
                "allow_squash_merge": False,
                "allow_rebase_merge": False,
            })

    def test_one_merge_method_is_enough(self):
        block = {
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "allow_rebase_merge": False,
        }
        self.assertEqual(self.settings(block), block)


class GitHubReadCase(unittest.TestCase):
    def test_empty_metadata_reads_as_empty_strings(self):
        meta = repo_meta.metadata_from_github(
            {"description": None, "homepageUrl": None, "repositoryTopics": None}
        )
        self.assertEqual(meta, repo_meta.Metadata("", "", ()))

    def test_topics_are_read_and_sorted(self):
        meta = repo_meta.metadata_from_github(
            {"description": "d", "homepageUrl": "", "repositoryTopics": [
                {"name": "zebra"}, {"name": "alpha"},
            ]}
        )
        self.assertEqual(meta.topics, ("alpha", "zebra"))

    def test_a_nameless_topic_is_an_error(self):
        with self.assertRaises(repo_meta.GitHubError):
            repo_meta.metadata_from_github({"repositoryTopics": [{"id": "x"}]})

    def test_settings_are_read_from_the_gh_document(self):
        meta = repo_meta.metadata_from_github({
            "defaultBranchRef": {"name": "main"},
            "hasWikiEnabled": True,
            "squashMergeAllowed": False,
        })
        self.assertEqual(meta.settings, {
            "default_branch": "main",
            "has_wiki": True,
            "allow_squash_merge": False,
        })

    def test_a_repository_with_no_branch_reports_no_default_branch(self):
        # A repository with no commit has a null defaultBranchRef.
        meta = repo_meta.metadata_from_github({"defaultBranchRef": None})
        self.assertNotIn("default_branch", meta.settings)

    def test_every_managed_setting_is_requested_from_gh(self):
        for key in repo_meta.BOOLEAN_SETTINGS:
            self.assertIn(repo_meta.BOOLEAN_SETTINGS[key][0], repo_meta.VIEW_FIELDS)
        self.assertIn("defaultBranchRef", repo_meta.VIEW_FIELDS)


class PlanCase(unittest.TestCase):
    def test_identical_metadata_is_exact(self):
        meta = repo_meta.Metadata("d", "https://example.com", ("a",))
        self.assertTrue(repo_meta.build_plan(meta, meta).exact)

    def test_an_empty_repository_is_all_additions(self):
        desired = repo_meta.Metadata("d", "", ("a", "b"))
        plan = repo_meta.build_plan(desired, repo_meta.Metadata())
        self.assertEqual([change.kind for change in plan.changes], ["SET", "ADD", "ADD"])
        self.assertEqual(plan.destructive, ())

    def test_removing_a_topic_is_destructive(self):
        plan = repo_meta.build_plan(
            repo_meta.Metadata("d"), repo_meta.Metadata("d", "", ("stale",))
        )
        self.assertEqual([change.kind for change in plan.changes], ["REMOVE"])
        self.assertEqual(len(plan.destructive), 1)

    def test_clearing_a_field_is_destructive(self):
        plan = repo_meta.build_plan(
            repo_meta.Metadata(""), repo_meta.Metadata("old")
        )
        self.assertEqual([change.kind for change in plan.changes], ["CLEAR"])
        self.assertEqual(len(plan.destructive), 1)

    def test_replacing_a_description_is_not_destructive(self):
        plan = repo_meta.build_plan(
            repo_meta.Metadata("new"), repo_meta.Metadata("old")
        )
        self.assertEqual([change.kind for change in plan.changes], ["SET"])
        self.assertEqual(plan.destructive, ())


class SettingsPlanCase(unittest.TestCase):
    def plan(self, desired, current):
        return repo_meta.build_plan(
            repo_meta.Metadata(settings=desired),
            repo_meta.Metadata(settings=current),
        )

    def test_an_undeclared_setting_is_not_compared(self):
        plan = self.plan({}, {"has_wiki": True, "default_branch": "trunk"})
        self.assertTrue(plan.exact)

    def test_enabling_a_surface_is_not_destructive(self):
        plan = self.plan({"has_discussions": True}, {"has_discussions": False})
        self.assertEqual([c.kind for c in plan.changes], ["ENABLE"])
        self.assertEqual(plan.destructive, ())

    def test_disabling_a_surface_is_destructive(self):
        # The wiki was on while the audit recorded it off. Turning it off
        # removes a surface, so it needs a human.
        plan = self.plan({"has_wiki": False}, {"has_wiki": True})
        self.assertEqual([c.kind for c in plan.changes], ["DISABLE"])
        self.assertEqual(len(plan.destructive), 1)
        self.assertEqual(plan.changes[0].before, "on")
        self.assertEqual(plan.changes[0].after, "off")

    def test_retargeting_the_default_branch_is_destructive(self):
        plan = self.plan({"default_branch": "main"}, {"default_branch": "master"})
        self.assertEqual([c.kind for c in plan.changes], ["RETARGET"])
        self.assertEqual(len(plan.destructive), 1)

    def test_a_setting_gh_did_not_report_is_drift_this_side_cannot_repair(self):
        plan = self.plan({"has_wiki": False}, {})
        self.assertEqual([c.kind for c in plan.changes], ["UNKNOWN"])
        self.assertFalse(plan.exact)

    def test_matching_settings_are_exact(self):
        block = {"default_branch": "main", "has_wiki": False}
        self.assertTrue(self.plan(block, dict(block)).exact)

    def test_the_shipped_manifest_is_exact_against_itself(self):
        meta = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        self.assertTrue(repo_meta.build_plan(meta, meta).exact)

    def test_every_change_renders(self):
        plan = self.plan(
            {"default_branch": "main", "has_wiki": False, "has_discussions": True},
            {"default_branch": "master", "has_wiki": True, "has_discussions": False},
        )
        rendered = repo_meta.render_plan(plan)
        for token in ("RETARGET", "DISABLE", "ENABLE", "has_wiki", "master"):
            self.assertIn(token, rendered)


class ApplyCase(unittest.TestCase):
    def calls_for(self, desired, current):
        plan = repo_meta.build_plan(desired, current)
        with mock.patch.object(repo_meta, "_run_gh", return_value="") as run:
            repo_meta.apply_plan("owner/name", plan)
        return [call.args[0] for call in run.call_args_list]

    def test_about_fields_go_in_one_edit(self):
        calls = self.calls_for(
            repo_meta.Metadata("d", "https://example.com"), repo_meta.Metadata()
        )
        self.assertEqual(calls, [[
            "repo", "edit", "owner/name",
            "--description", "d",
            "--homepage", "https://example.com",
        ]])

    def test_every_value_is_a_separate_argument(self):
        # A value that reaches gh as its own argument is never parsed by a
        # shell, whatever it contains.
        calls = self.calls_for(
            repo_meta.Metadata("a; rm -rf /"), repo_meta.Metadata()
        )
        self.assertIn("a; rm -rf /", calls[0])

    def test_topics_are_added_and_removed_in_one_edit(self):
        calls = self.calls_for(
            repo_meta.Metadata("", "", ("keep", "new")),
            repo_meta.Metadata("", "", ("keep", "stale")),
        )
        self.assertEqual(calls, [[
            "repo", "edit", "owner/name",
            "--add-topic", "new",
            "--remove-topic", "stale",
        ]])

    def test_an_exact_repository_is_not_edited(self):
        meta = repo_meta.Metadata("d", "", ("a",))
        self.assertEqual(self.calls_for(meta, meta), [])

    def test_settings_go_in_their_own_edit(self):
        calls = self.calls_for(
            repo_meta.Metadata(settings={"has_wiki": False, "has_issues": True}),
            repo_meta.Metadata(settings={"has_wiki": True, "has_issues": False}),
        )
        self.assertEqual(calls, [[
            "repo", "edit", "owner/name",
            "--enable-issues=true",
            "--enable-wiki=false",
        ]])

    def test_the_default_branch_is_written_as_its_own_argument(self):
        calls = self.calls_for(
            repo_meta.Metadata(settings={"default_branch": "main"}),
            repo_meta.Metadata(settings={"default_branch": "master"}),
        )
        self.assertEqual(calls, [[
            "repo", "edit", "owner/name", "--default-branch", "main",
        ]])

    def test_a_setting_gh_did_not_report_is_not_written(self):
        # This side does not know what the write would overwrite.
        calls = self.calls_for(
            repo_meta.Metadata(settings={"has_wiki": False}), repo_meta.Metadata()
        )
        self.assertEqual(calls, [])

    def test_about_topics_and_settings_are_three_edits(self):
        calls = self.calls_for(
            repo_meta.Metadata("d", "", ("new",), {"has_wiki": False}),
            repo_meta.Metadata("", "", ("stale",), {"has_wiki": True}),
        )
        self.assertEqual(len(calls), 3)
        self.assertIn("--description", calls[0])
        self.assertIn("--add-topic", calls[1])
        self.assertIn("--enable-wiki=false", calls[2])


class CommandCase(unittest.TestCase):
    def setUp(self):
        # The command prints its plan. A test asserts on the exit code, so the
        # plan is captured instead of mixed into the verification output.
        for stream in ("stdout", "stderr"):
            patch = mock.patch.object(sys, stream, io.StringIO())
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, argv, current, stdin_tty=False):
        with mock.patch.object(repo_meta, "resolve_repo", return_value="owner/name"), \
             mock.patch.object(repo_meta, "read_current", return_value=current), \
             mock.patch.object(repo_meta, "apply_plan") as apply, \
             mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: stdin_tty)):
            code = repo_meta.main(argv)
        return code, apply

    def test_check_reports_drift_without_changing_anything(self):
        code, apply = self.run_main(["check"], repo_meta.Metadata())
        self.assertEqual(code, repo_meta.EXIT_DRIFT)
        apply.assert_not_called()

    def test_check_is_clean_when_the_repository_matches(self):
        desired = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        code, apply = self.run_main(["check"], desired)
        self.assertEqual(code, repo_meta.EXIT_OK)
        apply.assert_not_called()

    def test_a_dry_run_changes_nothing(self):
        code, apply = self.run_main(["sync", "--dry-run"], repo_meta.Metadata())
        self.assertEqual(code, repo_meta.EXIT_OK)
        apply.assert_not_called()

    def test_a_destructive_sync_is_refused_without_a_terminal(self):
        current = repo_meta.Metadata("", "", ("stale-topic",))
        code, apply = self.run_main(["sync"], current)
        self.assertEqual(code, repo_meta.EXIT_REFUSED)
        apply.assert_not_called()

    def test_disabling_a_surface_is_refused_without_a_terminal(self):
        desired = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        current = dataclasses.replace(
            desired, settings={**desired.settings, "has_wiki": True}
        )
        code, apply = self.run_main(["sync"], current)
        self.assertEqual(code, repo_meta.EXIT_REFUSED)
        apply.assert_not_called()

    def test_settings_drift_alone_is_reported_by_check(self):
        desired = repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json")
        current = dataclasses.replace(
            desired, settings={**desired.settings, "has_wiki": True}
        )
        code, apply = self.run_main(["check"], current)
        self.assertEqual(code, repo_meta.EXIT_DRIFT)
        apply.assert_not_called()

    def test_yes_allows_a_destructive_sync(self):
        current = repo_meta.Metadata("", "", ("stale-topic",))
        with mock.patch.object(repo_meta, "resolve_repo", return_value="owner/name"), \
             mock.patch.object(repo_meta, "read_current", side_effect=[
                 current,
                 repo_meta.load_manifest(ROOT / "manifests" / "github-metadata.json"),
             ]), \
             mock.patch.object(repo_meta, "apply_plan") as apply:
            code = repo_meta.main(["sync", "--yes"])
        self.assertEqual(code, repo_meta.EXIT_OK)
        apply.assert_called_once()

    def test_a_sync_that_does_not_converge_fails(self):
        empty = repo_meta.Metadata()
        with mock.patch.object(repo_meta, "resolve_repo", return_value="owner/name"), \
             mock.patch.object(repo_meta, "read_current", side_effect=[empty, empty]), \
             mock.patch.object(repo_meta, "apply_plan"):
            code = repo_meta.main(["sync"])
        self.assertEqual(code, repo_meta.EXIT_VERIFY)

    def test_a_bad_repository_argument_is_a_usage_error(self):
        with mock.patch.object(repo_meta, "read_current", return_value=repo_meta.Metadata()):
            self.assertEqual(repo_meta.main(["check", "--repo", "name"]), repo_meta.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main(verbosity=0)
