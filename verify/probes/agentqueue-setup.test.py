#!/usr/bin/env python3
"""agentq setup: repository enrollment that starts no work.

Two properties matter more than the report itself.

    setup changes GitHub in no way, and it never rewrites a label
    setup runs no backlog work

Every test drives the real implementation with injected readers, so nothing
here reaches GitHub, git over the network or Podman.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import agentqueue_fakes as fakes  # noqa: E402
from agentqueue import cli as cli_mod  # noqa: E402
from agentqueue import policy as policy_mod  # noqa: E402
from agentqueue import setup as setup_mod  # noqa: E402

DEFAULT_POLICY = os.path.join(_ROOT, "config", "agentqueue", "policy.default.json")


def a_policy(**overrides):
    pol = policy_mod.load("/nonexistent", DEFAULT_POLICY)
    for key, value in overrides.items():
        setattr(pol, key, value)
    return pol


def canonical_labels():
    """The repository labels of a repository that matches the catalog."""
    return [dict(item) for item in setup_mod.workflow_labels(_ROOT)]


def git(args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


class TestCheckDetection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, content):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_a_pnpm_repository_with_a_check_script(self):
        self.write("pnpm-lock.yaml", "lockfileVersion: 9\n")
        self.write("package.json", json.dumps({"scripts": {"check": "tsc"}}))
        found = setup_mod.detect_checks(self.root)
        self.assertEqual(
            found.commands, ("pnpm install --frozen-lockfile", "pnpm check")
        )
        self.assertIn("package.json", found.evidence)

    def test_an_npm_repository_falls_back_to_the_test_script(self):
        self.write("package-lock.json", "{}")
        self.write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self.assertEqual(
            setup_mod.detect_checks(self.root).commands, ("npm ci", "npm run test")
        )

    def test_a_lockfile_with_no_usable_script_suggests_the_install_only(self):
        self.write("pnpm-lock.yaml", "lockfileVersion: 9\n")
        self.write("package.json", json.dumps({"scripts": {"build": "tsc"}}))
        self.assertEqual(
            setup_mod.detect_checks(self.root).commands,
            ("pnpm install --frozen-lockfile",),
        )

    def test_an_executable_verify_script_is_the_check(self):
        path = self.write("verify.sh", "#!/bin/sh\n")
        os.chmod(path, 0o755)
        self.assertEqual(setup_mod.detect_checks(self.root).commands, ("./verify.sh",))

    def test_a_repository_with_no_evidence_gets_no_suggestion(self):
        found = setup_mod.detect_checks(self.root)
        self.assertEqual(found.commands, ())
        self.assertTrue(found.evidence)

    def test_unreadable_package_json_does_not_raise(self):
        self.write("pnpm-lock.yaml", "lockfileVersion: 9\n")
        self.write("package.json", "{ not json")
        self.assertEqual(
            setup_mod.detect_checks(self.root).commands,
            ("pnpm install --frozen-lockfile",),
        )

    def test_workflow_files_are_found_by_both_extensions(self):
        os.makedirs(os.path.join(self.root, ".github", "workflows"))
        self.write(os.path.join(".github", "workflows", "ci.yml"), "on: push\n")
        self.write(os.path.join(".github", "workflows", "release.yaml"), "on: push\n")
        self.assertEqual(
            setup_mod.detect_workflows(self.root), ("ci.yml", "release.yaml")
        )


class TestTheLabelCatalog(unittest.TestCase):
    def test_the_workflow_group_holds_the_lifecycle_labels(self):
        names = {item["name"] for item in setup_mod.workflow_labels(_ROOT)}
        for label in ("ready-for-agent", "agent-in-progress", "ready-for-human",
                      "agent-failed"):
            self.assertIn(label, names)

    def test_the_workflow_group_holds_nothing_else(self):
        # The catalog also carries issue-taxonomy groups. A run must not treat
        # one of those as a lifecycle label, so the selection stays exact.
        names = {item["name"] for item in setup_mod.workflow_labels(_ROOT)}
        self.assertEqual(names, {
            "ready-for-agent", "agent-in-progress", "ready-for-human",
            "agent-failed", "wayfinder",
        })

    def test_a_missing_catalog_is_reported_and_not_guessed(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(setup_mod.SetupError):
                setup_mod.workflow_labels(empty)


class TestLabelDrift(unittest.TestCase):
    def setUp(self):
        self.desired = canonical_labels()
        self.lifecycle = ("ready-for-agent", "agent-in-progress",
                          "ready-for-human", "agent-failed")

    def drift(self, current):
        return setup_mod.label_drift(self.desired, self.lifecycle, current)

    def test_an_exact_repository_has_no_drift(self):
        self.assertEqual(self.drift(canonical_labels()), ())

    def test_an_extra_label_is_not_drift(self):
        current = canonical_labels()
        current.append({"name": "triage", "color": "ffffff", "description": "x"})
        self.assertEqual(self.drift(current), ())

    def test_a_missing_label_is_named(self):
        current = [i for i in canonical_labels() if i["name"] != "agent-failed"]
        self.assertEqual(self.drift(current), ("agent-failed: missing",))

    def test_a_wrong_color_is_named(self):
        current = canonical_labels()
        current[0]["color"] = "123456"
        drift = self.drift(current)
        self.assertEqual(len(drift), 1)
        self.assertIn("color 123456", drift[0])

    def test_the_color_comparison_ignores_case(self):
        current = canonical_labels()
        current[0]["color"] = current[0]["color"].upper()
        self.assertEqual(self.drift(current), ())

    def test_a_wrong_description_is_named(self):
        current = canonical_labels()
        current[0]["description"] = "something else"
        self.assertIn("description", self.drift(current)[0])

    def test_a_renamed_lifecycle_label_only_has_to_exist(self):
        current = canonical_labels()
        current.append({"name": "queue-me", "color": "aaaaaa", "description": ""})
        drift = setup_mod.label_drift(
            self.desired, ("queue-me", "agent-in-progress", "ready-for-human",
                           "agent-failed"), current)
        self.assertEqual(drift, ())

    def test_a_renamed_lifecycle_label_that_does_not_exist_is_drift(self):
        drift = setup_mod.label_drift(
            self.desired, ("queue-me",), canonical_labels())
        self.assertEqual(len(drift), 1)
        self.assertIn("queue-me", drift[0])


class TestThePolicyDraft(unittest.TestCase):
    def test_every_gate_starts_closed(self):
        draft = setup_mod.policy_draft(a_policy(), "trunk", ("./verify.sh",))
        self.assertFalse(draft["autoMerge"])
        self.assertFalse(draft["mergeWithoutReview"])
        self.assertEqual(draft["reviewPolicy"], "optional")
        self.assertEqual(draft["requiredChecks"], [])

    def test_the_detected_facts_are_used(self):
        draft = setup_mod.policy_draft(a_policy(), "trunk", ("./verify.sh",))
        self.assertEqual(draft["baseBranch"], "trunk")
        self.assertEqual(draft["checks"], ["./verify.sh"])

    def test_an_unknown_default_branch_keeps_the_policy_value(self):
        draft = setup_mod.policy_draft(a_policy(baseBranch="release"), "", ())
        self.assertEqual(draft["baseBranch"], "release")

    def test_the_draft_is_a_valid_policy(self):
        draft = setup_mod.policy_draft(a_policy(), "main", ("./verify.sh",))
        policy_mod.overlay(policy_mod.Policy(), draft, "draft").validate()


class InspectCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        with open(os.path.join(self.root, ".agentqueue.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}\n")

    def inspect(self, pol=None, **overrides):
        options = {
            "read_default_branch": lambda: "main",
            "read_labels": canonical_labels,
            "gh_ready": True,
            "ssh_agent": "/run/agent.sock",
            "git": None,
        }
        options.update(overrides)
        return setup_mod.inspect(
            self.root, "acme", "widget", pol or a_policy(checks=("./verify.sh",)),
            _ROOT, **options)

    def find(self, report, key):
        for finding in report.findings:
            if finding.key == key:
                return finding
        raise AssertionError(f"no finding named {key}")


class TestTheReport(InspectCase):
    def test_a_prepared_repository_is_ready(self):
        report = self.inspect()
        self.assertTrue(report.ready, [f.detail for f in report.gaps])
        self.assertEqual(report.repository, "acme/widget")

    def test_a_repository_policy_file_is_recognised(self):
        self.assertEqual(self.find(self.inspect(), "policy").state, setup_mod.OK)

    def test_a_repository_with_no_policy_of_its_own_is_offered_one(self):
        os.remove(os.path.join(self.root, ".agentqueue.json"))
        finding = self.find(self.inspect(pol=a_policy(sources=(DEFAULT_POLICY,))),
                            "policy")
        self.assertEqual(finding.state, setup_mod.ACTION)
        self.assertIn("--write-policy", finding.remedy)

    def test_the_built_in_default_alone_is_not_repository_policy(self):
        os.remove(os.path.join(self.root, ".agentqueue.json"))
        pol = a_policy(sources=(DEFAULT_POLICY,), checks=("./verify.sh",))
        self.assertEqual(self.find(self.inspect(pol=pol), "policy").state,
                         setup_mod.ACTION)

    def test_a_local_policy_file_counts_as_repository_policy(self):
        os.remove(os.path.join(self.root, ".agentqueue.json"))
        pol = a_policy(sources=(DEFAULT_POLICY, "/home/x/.config/agentqueue/r.json"),
                       checks=("./verify.sh",))
        self.assertEqual(self.find(self.inspect(pol=pol), "policy").state,
                         setup_mod.OK)

    def test_a_base_branch_that_github_contradicts_is_a_gap(self):
        report = self.inspect(read_default_branch=lambda: "trunk")
        finding = self.find(report, "base-branch")
        self.assertEqual(finding.state, setup_mod.GAP)
        self.assertIn("trunk", finding.detail)
        self.assertFalse(report.ready)

    def test_a_github_read_that_fails_is_a_gap_and_not_an_ok(self):
        def boom():
            raise RuntimeError("network")

        report = self.inspect(read_default_branch=boom)
        self.assertEqual(self.find(report, "base-branch").state, setup_mod.GAP)

    def test_a_default_branch_github_did_not_name_is_a_gap(self):
        # A repository that is not there, or that this account cannot see,
        # answers with nothing. An absent finding would read as an answer.
        report = self.inspect(read_default_branch=lambda: "")
        finding = self.find(report, "base-branch")
        self.assertEqual(finding.state, setup_mod.GAP)
        self.assertIn("acme/widget", finding.detail)
        self.assertFalse(report.ready)

    def test_a_github_read_that_fails_reports_one_base_branch_finding(self):
        def boom():
            raise RuntimeError("network")

        report = self.inspect(read_default_branch=boom)
        found = [f for f in report.findings if f.key == "base-branch"]
        self.assertEqual(len(found), 1)

    def test_an_unread_github_default_branch_is_a_note(self):
        report = self.inspect(read_default_branch=None)
        self.assertEqual(self.find(report, "base-branch").state, setup_mod.NOTE)

    def test_missing_checks_are_a_suggestion_and_do_not_block(self):
        report = self.inspect(pol=a_policy(checks=()))
        self.assertEqual(self.find(report, "checks").state, setup_mod.ACTION)
        self.assertTrue(report.ready)

    def test_required_checks_with_no_workflow_file_are_a_gap(self):
        report = self.inspect(pol=a_policy(checks=("x",), requiredChecks=("Quality",)))
        self.assertEqual(self.find(report, "ci").state, setup_mod.GAP)

    def test_a_workflow_file_satisfies_the_ci_finding(self):
        os.makedirs(os.path.join(self.root, ".github", "workflows"))
        with open(os.path.join(self.root, ".github", "workflows", "ci.yml"), "w",
                  encoding="utf-8") as handle:
            handle.write("on: push\n")
        report = self.inspect(pol=a_policy(checks=("x",), requiredChecks=("Quality",)))
        self.assertEqual(self.find(report, "ci").state, setup_mod.OK)

    def test_label_drift_is_a_gap_that_names_the_repair_command(self):
        current = [i for i in canonical_labels() if i["name"] != "ready-for-agent"]
        report = self.inspect(read_labels=lambda: current)
        finding = self.find(report, "labels")
        self.assertEqual(finding.state, setup_mod.GAP)
        self.assertIn("repo-labels sync --repo acme/widget", finding.remedy)
        self.assertIn("read repo-labels check first", finding.remedy)

    def test_labels_that_could_not_be_read_are_never_reported_as_ok(self):
        def boom():
            raise RuntimeError("403")

        self.assertEqual(self.find(self.inspect(read_labels=boom), "labels").state,
                         setup_mod.GAP)

    def test_unauthenticated_gh_is_a_gap(self):
        self.assertEqual(self.find(self.inspect(gh_ready=False), "auth").state,
                         setup_mod.GAP)

    def test_a_missing_ssh_agent_is_a_gap(self):
        self.assertEqual(self.find(self.inspect(ssh_agent=""), "ssh").state,
                         setup_mod.GAP)

    def test_a_missing_base_ref_is_a_gap(self):
        class NoRef:
            def rev_parse(self, ref):
                return None

        self.assertEqual(self.find(self.inspect(git=NoRef()), "base-ref").state,
                         setup_mod.GAP)

    def test_the_merge_gates_are_reported_and_never_changed(self):
        pol = a_policy(checks=("x",), autoMerge=False)
        finding = self.find(self.inspect(pol=pol), "gates")
        self.assertEqual(finding.state, setup_mod.NOTE)
        self.assertIn("autoMerge False", finding.detail)

    def test_the_rendered_report_names_every_gap(self):
        text = "\n".join(setup_mod.render(self.inspect(gh_ready=False)))
        self.assertIn("gap(s) block a run", text)
        self.assertIn("agentq changed nothing", text)

    def test_the_rendered_report_of_a_ready_repository_points_at_plan(self):
        text = "\n".join(setup_mod.render(self.inspect()))
        self.assertIn("agentq plan", text)

    def test_the_json_shape_is_stable(self):
        document = self.inspect().as_dict()
        self.assertEqual(document["repository"], "acme/widget")
        self.assertTrue(document["ready"])
        for finding in document["findings"]:
            self.assertEqual(
                sorted(finding), ["detail", "key", "remedy", "state", "title"])


class TestTheCommand(unittest.TestCase):
    """The command surface, against a real working tree and a fake GitHub."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.remote = os.path.join(self.root, "work.git")
        self.work = os.path.join(self.root, "work")
        os.makedirs(self.work)
        git(["init", "--quiet", "--bare", "-b", "main", self.remote], self.root)
        git(["init", "--quiet", "-b", "main", "."], self.work)
        git(["remote", "add", "origin", self.remote], self.work)
        with open(os.path.join(self.work, "README.md"), "w", encoding="utf-8") as h:
            h.write("# demo\n")
        path = os.path.join(self.work, "verify.sh")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        git(["add", "-A"], self.work)
        git(["-c", "user.name=A Person", "-c", "user.email=person@example.invalid",
             "commit", "--quiet", "-m", "first"], self.work)
        git(["push", "--quiet", "-u", "origin", "main"], self.work)
        git(["fetch", "--quiet", "origin"], self.work)

        # The slug comes from the git remote of the working tree, not from
        # the client. A double that named another repository would hide that.
        self.slug = f"{os.path.basename(self.root)}/work"
        self.github = fakes.FakeGitHub("acme", "widget")
        self.github.repository_labels = canonical_labels()
        self.runner = fakes.FakeRunner(None)
        self._cwd = os.getcwd()
        self.addCleanup(self._restore)

    def _restore(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def invoke(self, argv, gh_ready=True):
        github, runner, transport = (
            cli_mod.GitHub, cli_mod.AgentboxRunner, cli_mod.GhTransport)
        outer = self

        class Transport:
            def available(self):
                return True

            def run(self, args, stdin=None):
                return (0 if gh_ready else 1), "", ""

        cli_mod.GitHub = lambda owner, name, dry_run=False: outer._github(dry_run)
        cli_mod.AgentboxRunner = lambda *a, **k: outer.runner
        cli_mod.GhTransport = Transport
        out, err = io.StringIO(), io.StringIO()
        os.chdir(self.work)
        os.environ["SSH_AUTH_SOCK"] = "/run/agent.sock"
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli_mod.main(argv, install_root=_ROOT)
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 2
        finally:
            (cli_mod.GitHub, cli_mod.AgentboxRunner,
             cli_mod.GhTransport) = github, runner, transport
            os.chdir(self._cwd)
        return code, out.getvalue(), err.getvalue()

    def _github(self, dry_run):
        self.github.dry_run = dry_run
        return self.github

    def policy_file(self):
        return os.path.join(self.work, ".agentqueue.json")

    # ------------------------------------------------------------- tests --

    def test_setup_is_a_command(self):
        self.assertEqual(cli_mod.build_parser().parse_args(["setup"]).command,
                         "setup")

    def test_setup_reports_and_changes_nothing_on_github(self):
        code, out, _ = self.invoke(["setup"])
        self.assertIn(code, (cli_mod.EXIT_OK, cli_mod.EXIT_NOT_READY))
        self.assertIn("agentq setup", out)
        self.assertEqual(self.github.mutations, [])

    def test_setup_runs_no_backlog_work(self):
        self.github.add_issue(7, "Do the thing", labels=("ready-for-agent",))
        self.invoke(["setup"])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.github.mutations, [])
        self.assertEqual(
            git(["for-each-ref", "--format=%(refname:short)"], self.remote), "main")

    def test_setup_never_writes_a_label(self):
        self.github.repository_labels = []
        code, out, _ = self.invoke(["setup"])
        self.assertEqual(code, cli_mod.EXIT_NOT_READY)
        self.assertIn(f"repo-labels sync --repo {self.slug}", out)
        self.assertEqual(self.github.mutations, [])

    def test_setup_without_write_policy_writes_no_file(self):
        self.invoke(["setup"])
        self.assertFalse(os.path.exists(self.policy_file()))

    def test_write_policy_writes_the_detected_policy(self):
        code, out, _ = self.invoke(["setup", "--write-policy"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("wrote", out)
        with open(self.policy_file(), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(written["baseBranch"], "main")
        self.assertEqual(written["checks"], ["./verify.sh"])
        self.assertFalse(written["autoMerge"])
        self.assertEqual(self.github.mutations, [])

    def test_write_policy_refuses_to_replace_an_existing_file(self):
        self.invoke(["setup", "--write-policy"])
        with open(self.policy_file(), encoding="utf-8") as handle:
            before = handle.read()
        code, out, _ = self.invoke(["setup", "--write-policy"])
        self.assertEqual(code, cli_mod.EXIT_USAGE)
        self.assertIn("--force", out)
        with open(self.policy_file(), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_force_replaces_the_file(self):
        self.invoke(["setup", "--write-policy"])
        with open(self.policy_file(), "w", encoding="utf-8") as handle:
            handle.write('{"version": 1, "maxRetries": 9}\n')
        code, _, _ = self.invoke(["setup", "--write-policy", "--force"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        with open(self.policy_file(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["maxRetries"], 2)

    def test_running_setup_twice_reaches_the_same_state(self):
        self.invoke(["setup", "--write-policy"])
        first = self.invoke(["setup"])
        second = self.invoke(["setup"])
        self.assertEqual(first, second)

    def test_a_repository_that_is_ready_exits_zero(self):
        self.invoke(["setup", "--write-policy"])
        code, _, _ = self.invoke(["setup"])
        self.assertEqual(code, cli_mod.EXIT_OK)

    def test_a_repository_with_a_gap_exits_not_ready(self):
        self.github.repository_labels = []
        code, _, _ = self.invoke(["setup"])
        self.assertEqual(code, cli_mod.EXIT_NOT_READY)

    def test_unauthenticated_gh_does_not_stop_the_report(self):
        code, out, _ = self.invoke(["setup"], gh_ready=False)
        self.assertEqual(code, cli_mod.EXIT_NOT_READY)
        self.assertIn("gh auth login", out)

    def test_json_output_is_one_document(self):
        code, out, _ = self.invoke(["setup", "--json"])
        self.assertIn(code, (cli_mod.EXIT_OK, cli_mod.EXIT_NOT_READY))
        self.assertEqual(json.loads(out)["repository"], self.slug)

    def test_setup_outside_a_working_tree_is_a_usage_error(self):
        elsewhere = os.path.join(self.root, "nowhere")
        os.makedirs(elsewhere)
        code, _, err = self.invoke(["setup", "--repo", elsewhere])
        self.assertEqual(code, cli_mod.EXIT_USAGE)
        self.assertIn("not a Git working tree", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
