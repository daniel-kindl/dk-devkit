#!/usr/bin/env python3
"""Deterministic tests for the reusable repo-meta command."""

from __future__ import annotations

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


class ManifestCase(unittest.TestCase):
    def write(self, document):
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        json.dump(document, tmp)
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        return Path(tmp.name)

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
