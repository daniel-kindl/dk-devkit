#!/usr/bin/env python3
"""The agentqueue command surface: the command names and the repository.

Two things are proved here, and both are user-visible:

    "run" is the only command that starts a run, and "drain" is gone
    the repository is the current Git working tree unless --repo names one

The tests drive ``agentqueue.cli.main`` itself, against a real disposable Git
repository, so a passing case is the real argument parsing, the real
resolution and the real exit code. GitHub and agentbox stay doubles, because
neither can be created in a temporary directory.

    python3 verify/probes/agentqueue-cli.test.py

verify/85-agentqueue.sh runs this file, and it fails the module on any error.
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
from agentqueue.model import CheckRun, Outcome  # noqa: E402

READY = "ready-for-agent"
COMMANDS = ("run", "plan", "doctor", "policy", "init")
SCANNER = os.path.join(_ROOT, "bin", "scan-secrets")

# The identity agentbox stamps on every commit, read from the same manifest
# the coordinator reads. A branch whose commits carry another identity is not
# adopted, so the double must commit as agentbox does.
_IDENTITY = cli_mod._agent_identities(_ROOT) or ["Agent <agent@local>"]
AGENT_NAME, _, AGENT_EMAIL = _IDENTITY[0].partition(" <")
AGENT_EMAIL = AGENT_EMAIL.rstrip(">")

POLICY = {
    "version": 1,
    "baseBranch": "main",
    "issueLabel": READY,
    "checks": ["true"],
    "requiredChecks": [],
    "reviewPolicy": "optional",
    "mergeWithoutReview": True,
    "autoMerge": True,
    "mergeMethod": "squash",
    "maxParallel": 1,
    "maxRetries": 2,
}


def git(args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


class Repository:
    """A bare remote and a working clone, both disposable.

    ``name`` is used verbatim as a directory name, so a test can ask for a
    path that holds a space or a quote and prove that nothing along the way
    splits it.
    """

    def __init__(self, root, name="work", policy=None):
        self.remote = os.path.join(root, name + ".git")
        self.work = os.path.join(root, name)
        os.makedirs(self.work)
        git(["init", "--quiet", "--bare", "-b", "main", self.remote], root)
        git(["init", "--quiet", "-b", "main", "."], self.work)
        git(["remote", "add", "origin", self.remote], self.work)
        self.write(".agentqueue.json", json.dumps(policy or POLICY, indent=2) + "\n")
        self.write("README.md", "# demo\n")
        git(["add", "-A"], self.work)
        git(["-c", "user.name=A Person", "-c", "user.email=person@example.invalid",
             "commit", "--quiet", "-m", "first"], self.work)
        git(["push", "--quiet", "-u", "origin", "main"], self.work)
        git(["fetch", "--quiet", "origin"], self.work)

    def write(self, path, content):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)

    def subdir(self, name="src/deep"):
        full = os.path.join(self.work, name)
        os.makedirs(full, exist_ok=True)
        return full


class CommittingRunner(fakes.FakeRunner):
    """An agentbox double that really commits into the disposable clone."""

    def __init__(self, work, script=None):
        super().__init__(None, script)
        self.work = work

    def run(self, repo, branch, prompt_file, base_ref, continuation=False,
            log_name="agentbox", log_dir="", on_event=None, on_raw=None):
        from agentqueue.model import classify_agentbox_exit
        from agentqueue.runner import AgentRun

        step = self.script.pop(0) if self.script else {}
        self.calls.append({"branch": branch, "continuation": continuation,
                           "log_name": log_name, "log_dir": log_dir})
        for item in step.get("events", []):
            if on_event is not None:
                on_event(item)
        for line in step.get("raw", []):
            if on_raw is not None:
                on_raw(line)
        start = branch if continuation else "origin/main"
        git(["checkout", "--quiet", "-B", branch, start], self.work)
        path = step.get("path", "src/thing.mjs")
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(step.get("content", "export const ok = 1;\n"))
        git(["add", "--", path], self.work)
        git(["-c", f"user.name={AGENT_NAME}", "-c", f"user.email={AGENT_EMAIL}",
             "commit", "--quiet", "-m", "feat: implement the issue"], self.work)
        git(["checkout", "--quiet", "main"], self.work)
        sha = git(["rev-parse", branch], self.work)
        summary = {
            "checksPassed": True, "failedChecks": [], "fixRounds": 0,
            "review": {"skipped": True, "reason": "no credential"},
            "resultCommit": sha,
        }
        return AgentRun(0, classify_agentbox_exit(0, ""), "", summary, 1, ["agentbox"])


class CliCase(unittest.TestCase):
    """One disposable repository, and a ``main`` that cannot reach GitHub."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.repo = Repository(self.root)
        self.state = os.path.join(self.root, "state")
        self.github = fakes.FakeGitHub("acme", "widget")
        self.github.head_sha_source = lambda b: git(
            ["rev-parse", "--verify", "--quiet", b], self.repo.work
        ) if b else ""
        self.github.check_runs = lambda sha: [
            CheckRun("Quality", "completed", "success")
        ]
        self.runner = CommittingRunner(self.repo.work)
        self._cwd = os.getcwd()
        self.addCleanup(self._restore)

    def _restore(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    # ------------------------------------------------------------- driving --

    def invoke(self, argv, cwd=None, wire=True):
        """Run ``agentqueue`` argv and answer (exit code, stdout, stderr).

        ``wire`` replaces GitHub and agentbox with the doubles. It is off for
        the cases that must not reach either, so that a resolution failure
        cannot be hidden by a double that answers anyway.
        """
        github, runner = cli_mod.GitHub, cli_mod.AgentboxRunner
        if wire:
            outer = self
            cli_mod.GitHub = lambda owner, name, dry_run=False: outer._github(dry_run)
            cli_mod.AgentboxRunner = lambda *a, **k: outer.runner
        out, err = io.StringIO(), io.StringIO()
        os.chdir(cwd or self.repo.work)
        os.environ["AGENTQUEUE_STATE_DIR"] = self.state
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli_mod.main(argv, install_root=_ROOT)
                except SystemExit as exc:  # argparse refuses an argument
                    code = exc.code if isinstance(exc.code, int) else 2
        finally:
            cli_mod.GitHub, cli_mod.AgentboxRunner = github, runner
            os.chdir(self._cwd)
        return code, out.getvalue(), err.getvalue()

    def _github(self, dry_run):
        self.github.dry_run = dry_run
        return self.github

    def refs_on_the_remote(self):
        return git(["for-each-ref", "--format=%(refname:short)"], self.repo.remote)


# ------------------------------------------------------------ the commands --


class TestTheCommandNames(CliCase):
    def test_run_is_a_command(self):
        args = cli_mod.build_parser().parse_args(["run"])
        self.assertEqual(args.command, "run")

    def test_drain_is_rejected_as_an_unknown_command(self):
        code, _, err = self.invoke(["drain", "--repo", self.repo.work], wire=False)
        self.assertEqual(code, cli_mod.EXIT_USAGE)
        self.assertIn("invalid choice", err)
        self.assertIn("drain", err)

    def test_drain_is_rejected_with_no_option_at_all(self):
        code, _, _ = self.invoke(["drain"], wire=False)
        self.assertEqual(code, cli_mod.EXIT_USAGE)

    def test_drain_is_not_an_alias_of_anything(self):
        """No alias, no hidden command, no compatibility path.

        The parser is asked for its whole set of commands, so a command that
        exists but is left out of the help would still be found here.
        """
        import argparse

        found = set()
        for action in cli_mod.build_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                found.update(action.choices)
        self.assertEqual(found, set(COMMANDS))

    def test_the_help_advertises_run(self):
        code, out, _ = self.invoke(["--help"], wire=False)
        self.assertEqual(code, 0)
        self.assertIn("run", out)
        for command in COMMANDS:
            self.assertIn(command, out)

    def test_no_help_text_anywhere_advertises_drain(self):
        texts = [self.invoke(["--help"], wire=False)[1]]
        for command in COMMANDS:
            texts.append(self.invoke([command, "--help"], wire=False)[1])
        for text in texts:
            self.assertNotIn("drain", text.lower())

    def test_run_keeps_every_option_the_command_had(self):
        args = cli_mod.build_parser().parse_args([
            "run", "--repo", "/tmp/x", "--config", "/tmp/p.json",
            "--label", "L", "--base", "B", "--max-parallel", "3",
            "--max-retries", "5", "--merge-method", "rebase",
            "--no-auto-merge", "--once", "--dry-run", "--verbose",
        ])
        self.assertEqual(
            (args.repo, args.config, args.label, args.base, args.max_parallel,
             args.max_retries, args.merge_method, args.auto_merge, args.once,
             args.dry_run, args.verbose),
            ("/tmp/x", "/tmp/p.json", "L", "B", 3, 5, "rebase", False, True,
             True, True),
        )

    def test_run_allows_one_output_mode_at_a_time(self):
        for first, second in (
            ("--quiet", "--verbose"), ("--quiet", "--debug"),
            ("--verbose", "--debug"), ("--json", "--verbose"),
            ("--json", "--quiet"), ("--json", "--debug"),
        ):
            code, _, _ = self.invoke(["run", first, second], wire=False)
            self.assertEqual(code, cli_mod.EXIT_USAGE, f"{first} {second}")


# ------------------------------------------------- the repository is found --


class TestRepositoryResolution(CliCase):
    def resolve(self, path, cwd):
        os.chdir(cwd)
        try:
            return cli_mod._repo_root(path)
        finally:
            os.chdir(self._cwd)

    def test_the_current_working_tree_is_the_default(self):
        self.assertEqual(
            os.path.realpath(self.resolve(None, self.repo.work)),
            os.path.realpath(self.repo.work),
        )

    def test_a_subdirectory_resolves_to_the_top_of_the_tree(self):
        self.assertEqual(
            os.path.realpath(self.resolve(None, self.repo.subdir())),
            os.path.realpath(self.repo.work),
        )

    def test_a_linked_worktree_resolves_to_its_own_top(self):
        linked = os.path.join(self.root, "linked")
        git(["worktree", "add", "--quiet", "-b", "side", linked], self.repo.work)
        self.assertEqual(
            os.path.realpath(self.resolve(None, linked)),
            os.path.realpath(linked),
        )

    def test_repo_names_another_repository_from_anywhere(self):
        other = Repository(self.root, "other")
        self.assertEqual(
            os.path.realpath(self.resolve(other.work, self.repo.work)),
            os.path.realpath(other.work),
        )

    def test_repo_dot_still_means_here(self):
        self.assertEqual(
            os.path.realpath(self.resolve(".", self.repo.work)),
            os.path.realpath(self.repo.work),
        )

    def test_repo_expands_a_tilde(self):
        home = os.environ.get("HOME")
        os.environ["HOME"] = self.root
        try:
            self.assertEqual(
                os.path.realpath(self.resolve("~/work", self.root)),
                os.path.realpath(self.repo.work),
            )
        finally:
            if home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = home

    def test_a_path_with_a_space_and_a_quote_survives(self):
        odd = Repository(self.root, "a b 'c' d")
        self.assertEqual(
            os.path.realpath(self.resolve(odd.work, self.root)),
            os.path.realpath(odd.work),
        )
        self.assertEqual(
            os.path.realpath(self.resolve(None, odd.work)),
            os.path.realpath(odd.work),
        )

    def test_outside_a_working_tree_it_refuses_rather_than_guessing(self):
        bare = os.path.join(self.root, "empty")
        os.makedirs(bare)
        with self.assertRaises(cli_mod.SystemExit_) as caught:
            self.resolve(None, bare)
        self.assertEqual(caught.exception.code, cli_mod.EXIT_USAGE)
        self.assertIn("not a Git working tree", caught.exception.message)
        self.assertIn("--repo", caught.exception.message)

    def test_an_explicit_path_that_is_not_a_repository_is_refused(self):
        missing = os.path.join(self.root, "nowhere")
        with self.assertRaises(cli_mod.SystemExit_) as caught:
            self.resolve(missing, self.repo.work)
        self.assertEqual(caught.exception.code, cli_mod.EXIT_USAGE)
        self.assertIn(f"not a Git working tree: {missing}",
                      caught.exception.message)


class TestEveryCommandWorksWithoutRepo(CliCase):
    def test_policy(self):
        code, out, _ = self.invoke(["policy"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        # The slug comes from the origin remote of the resolved repository.
        self.assertIn(f"{os.path.basename(self.root)}/work", out)
        self.assertIn(os.path.join(self.repo.work, ".agentqueue.json"), out)

    def test_policy_json(self):
        code, out, _ = self.invoke(["policy", "--json"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertEqual(json.loads(out)["baseBranch"], "main")

    def test_doctor(self):
        code, out, _ = self.invoke(["doctor"])
        # 5 when this machine has no gh and no forwarded agent, 0 when it has.
        self.assertIn(code, (cli_mod.EXIT_OK, cli_mod.EXIT_NOT_READY))
        self.assertIn(os.path.realpath(self.repo.work), os.path.realpath(out))

    def test_plan(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        code, out, _ = self.invoke(["plan"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("DRY RUN", out)
        self.assertIn("mutations attempted: 0", out)
        self.assertEqual(self.github.mutations, [])
        self.assertEqual(self.refs_on_the_remote(), "main")

    def test_init(self):
        os.remove(os.path.join(self.repo.work, ".agentqueue.json"))
        code, out, _ = self.invoke(["init"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        target = os.path.join(self.repo.work, ".agentqueue.json")
        self.assertTrue(os.path.isfile(target))
        self.assertIn(target, out)

    def test_init_from_a_subdirectory_writes_at_the_top(self):
        os.remove(os.path.join(self.repo.work, ".agentqueue.json"))
        code, _, _ = self.invoke(["init"], cwd=self.repo.subdir())
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertTrue(
            os.path.isfile(os.path.join(self.repo.work, ".agentqueue.json"))
        )

    def test_run(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        code, _, _ = self.invoke(["run"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("agent/issue-85", self.refs_on_the_remote())

    def test_run_from_a_subdirectory(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        code, _, _ = self.invoke(["run"], cwd=self.repo.subdir())
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("agent/issue-85", self.refs_on_the_remote())


class TestRepoRemainsAnExplicitOverride(CliCase):
    def test_run_works_on_a_repository_the_shell_is_not_in(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        code, _, _ = self.invoke(["run", "--repo", self.repo.work], cwd=elsewhere)
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("agent/issue-85", self.refs_on_the_remote())

    def test_repo_wins_over_the_working_directory(self):
        other = Repository(self.root, "other")
        code, out, _ = self.invoke(["policy", "--repo", other.work],
                                   cwd=self.repo.work)
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn(other.work, out)

    def test_every_command_still_takes_repo(self):
        for command in COMMANDS:
            args = cli_mod.build_parser().parse_args(
                [command, "--repo", "/tmp/x"]
            )
            self.assertEqual(args.repo, "/tmp/x", command)


class TestOutsideARepositoryEveryCommandFails(CliCase):
    def setUp(self):
        super().setUp()
        self.outside = os.path.join(self.root, "outside")
        os.makedirs(self.outside)

    def test_each_command_exits_two_and_says_why(self):
        for command in COMMANDS:
            code, _, err = self.invoke([command], cwd=self.outside, wire=False)
            self.assertEqual(code, cli_mod.EXIT_USAGE, command)
            self.assertIn("not a Git working tree", err, command)
            self.assertIn(self.outside, err, command)
            self.assertIn("--repo", err, command)

    def test_nothing_is_created_where_it_refused(self):
        self.invoke(["init"], cwd=self.outside, wire=False)
        self.assertEqual(os.listdir(self.outside), [])


# ------------------------------------------------ run is what drain was ----


class TestRunDoesWhatDrainDid(CliCase):
    def test_a_whole_run_pushes_a_real_branch_and_merges(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        self.github.add_issue(86, "Use the module", labels=(READY,))
        self.github.dependencies[86] = [85]
        code, out, _ = self.invoke(["run"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        refs = self.refs_on_the_remote()
        self.assertIn("agent/issue-85", refs)
        self.assertIn("agent/issue-86", refs)
        self.assertEqual(len(self.github.merge_calls), 2)
        self.assertIn("#85", out)
        self.assertIn("#86", out)

    def test_once_stops_after_one_wave(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        self.github.add_issue(86, "Use the module", labels=(READY,))
        self.github.dependencies[86] = [85]
        code, _, _ = self.invoke(["run", "--once"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertEqual(len(self.github.merge_calls), 1)

    def test_run_dry_run_and_plan_print_the_same_thing(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        first = self.invoke(["run", "--dry-run"])
        self.github.mutations.clear()
        second = self.invoke(["plan"])
        self.assertEqual(first[0], cli_mod.EXIT_OK)
        self.assertEqual(first, second)
        self.assertEqual(self.refs_on_the_remote(), "main")

    def test_a_dry_run_changes_nothing(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        code, out, _ = self.invoke(["run", "--dry-run"])
        self.assertEqual(code, cli_mod.EXIT_OK)
        self.assertIn("mutations attempted: 0", out)
        self.assertEqual(self.github.mutations, [])
        self.assertEqual(self.runner.calls, [])

    def test_an_empty_queue_is_success(self):
        code, _, _ = self.invoke(["run"])
        self.assertEqual(code, cli_mod.EXIT_OK)

    def test_a_credential_in_the_diff_stops_the_queue_with_exit_four(self):
        self.github.add_issue(85, "Leaky", labels=(READY,))
        self.runner.script = [{
            "path": "src/leak.mjs",
            "content": "const key = 'AKIA" + "0123456789ABCDEF';\n",
        }]
        code, _, _ = self.invoke(["run"])
        self.assertEqual(code, cli_mod.EXIT_SECURITY)
        self.assertNotIn("agent/issue-85", self.refs_on_the_remote())

    def test_an_unusable_policy_exits_three(self):
        self.repo.write(".agentqueue.json", json.dumps({"version": 1,
                                                        "maxParallel": 0}))
        code, _, err = self.invoke(["run"])
        self.assertEqual(code, cli_mod.EXIT_POLICY)
        self.assertTrue(err.startswith("agentqueue:"))


class TestTheOutputModesStillWork(CliCase):
    def setUp(self):
        super().setUp()
        self.github.add_issue(85, "Implement the module", labels=(READY,))

    def text_of(self, *flags):
        code, out, _ = self.invoke(["run", *flags])
        self.assertEqual(code, cli_mod.EXIT_OK)
        return out

    def test_compact_is_the_default(self):
        out = self.text_of()
        self.assertIn("#85", out)
        # The compact view is the stage view, not the coordinator's notes.
        self.assertNotIn("run id", out)

    def test_verbose_adds_the_header_and_the_notes(self):
        out = self.text_of("--verbose")
        self.assertIn("run id", out)
        self.assertIn("repository", out)

    def test_quiet_says_less_than_compact(self):
        quiet = self.text_of("--quiet")
        self.github.merge_calls.clear()
        compact = self.text_of()
        self.assertLess(len(quiet.splitlines()), len(compact.splitlines()))

    def test_json_is_one_object_a_line(self):
        out = self.text_of("--json")
        records = [json.loads(line) for line in out.splitlines() if line.strip()]
        kinds = {r["event"] for r in records}
        self.assertIn("run.start", kinds)
        self.assertIn("issue.start", kinds)
        self.assertIn("run.end", kinds)

    def test_the_run_log_holds_the_transcript_at_every_level(self):
        self.text_of("--quiet")
        runs = os.path.join(self.state, "runs")
        logs = [
            os.path.join(runs, d, "queue.log")
            for d in os.listdir(runs)
            if os.path.isfile(os.path.join(runs, d, "queue.log"))
        ]
        self.assertTrue(logs)
        with open(logs[0], encoding="utf-8") as handle:
            self.assertIn("#85", handle.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
