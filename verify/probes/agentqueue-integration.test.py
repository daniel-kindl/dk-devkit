#!/usr/bin/env python3
"""agentqueue against a real, disposable Git repository.

The unit tests replace git. This file does not: it makes a bare "remote" and a
working clone in a temporary directory, and it drives the real ``Git`` class
against them. GitHub and agentbox stay doubles, because neither can be created
in a temporary directory.

What this proves that the unit tests cannot:

    the adoption audit reads real commits, real authors and real merge bases
    the push reaches a real remote, and a non-fast-forward push is refused
    the diff of a real branch reaches bin/scan-secrets
    a whole run leaves the real repository in the state it claims

Nothing here touches a repository a human owns.

    python3 verify/probes/agentqueue-integration.test.py
"""

from __future__ import annotations

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
from agentqueue.coordinator import Coordinator  # noqa: E402
from agentqueue.gitops import Git, GitError, scan_text_for_secrets  # noqa: E402
from agentqueue.model import CheckRun, Outcome  # noqa: E402

READY = "ready-for-agent"
AGENT_NAME, AGENT_EMAIL = "Agent", "agent@local"
HUMAN_NAME, HUMAN_EMAIL = "A Person", "person@example.invalid"
SCANNER = os.path.join(_ROOT, "bin", "scan-secrets")


def run(args, cwd, env=None):
    full = dict(os.environ)
    full.update(env or {})
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=full)
    if proc.returncode != 0:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def commit(repo, path, content, name=AGENT_NAME, email=AGENT_EMAIL, message="change"):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(content)
    run(["git", "add", "--", path], repo)
    run(
        ["git", "-c", f"user.name={name}", "-c", f"user.email={email}",
         "commit", "--quiet", "-m", message],
        repo,
    )


class RealRepository:
    """A bare remote and a working clone, both disposable."""

    def __init__(self, root):
        self.root = root
        self.remote = os.path.join(root, "remote.git")
        self.work = os.path.join(root, "work")
        run(["git", "init", "--quiet", "--bare", "-b", "main", self.remote], root)
        run(["git", "init", "--quiet", "-b", "main", self.work], root)
        run(["git", "remote", "add", "origin", self.remote], self.work)
        commit(self.work, "README.md", "# demo\n", HUMAN_NAME, HUMAN_EMAIL, "first")
        run(["git", "push", "--quiet", "-u", "origin", "main"], self.work)
        run(["git", "fetch", "--quiet", "origin"], self.work)

    def make_agent_branch(self, name, content="ok\n", author=AGENT_NAME,
                          email=AGENT_EMAIL, path="src/thing.mjs"):
        run(["git", "checkout", "--quiet", "-b", name, "origin/main"], self.work)
        commit(self.work, path, content, author, email, "feat: the thing")
        run(["git", "checkout", "--quiet", "main"], self.work)


class CommittingRunner(fakes.FakeRunner):
    """An agentbox double that really commits into the disposable repository."""

    def __init__(self, git, repo: RealRepository, script=None, content="ok\n"):
        super().__init__(git, script)
        self.repo = repo
        self.content = content

    def run(self, repo, branch, prompt_file, base_ref, continuation=False,
            log_name="agentbox", log_dir="", on_event=None, on_raw=None,
            effort=None):
        step = self.script.pop(0) if self.script else {}
        self.calls.append({"branch": branch, "continuation": continuation,
                           "prompt": fakes._read(prompt_file), "log_name": log_name,
                           "log_dir": log_dir})
        for item in step.get("events", []):
            if on_event is not None:
                on_event(item)
        if step.get("exit", 0) != 0:
            from agentqueue.model import classify_agentbox_exit
            from agentqueue.runner import AgentRun

            return AgentRun(step["exit"], classify_agentbox_exit(
                step["exit"], step.get("output", "")), step.get("output", ""),
                None, 1, ["agentbox"])

        work = self.repo.work
        start = branch if continuation else "origin/main"
        run(["git", "checkout", "--quiet", "-B", branch, start], work)
        commit(work, step.get("path", "src/thing.mjs"),
               step.get("content", self.content),
               message=step.get("message", "feat: implement the issue"))
        run(["git", "checkout", "--quiet", "main"], work)

        from agentqueue.model import classify_agentbox_exit
        from agentqueue.runner import AgentRun

        sha = run(["git", "rev-parse", branch], work)
        summary = {
            "checksPassed": step.get("checks_passed", True),
            "failedChecks": step.get("failed_checks", []),
            "fixRounds": step.get("fix_rounds", 0),
            "review": step.get("review", {"skipped": True, "reason": "no credential"}),
            "resultCommit": sha,
        }
        return AgentRun(0, classify_agentbox_exit(0, ""), "", summary, 1, ["agentbox"])


class IntegrationCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.repo = RealRepository(self.root)
        self.git = Git(self.repo.work)
        self.github = fakes.FakeGitHub()
        self.github.head_sha_source = lambda b: self.git.rev_parse(b) or ""
        self.policy = fakes.make_policy(
            autoMerge=True, mergeWithoutReview=True, checks=("true",),
        )
        self.state = os.path.join(self.root, "state")

    def tearDown(self):
        self._tmp.cleanup()

    def coordinator(self, runner, dry_run=False):
        return Coordinator(
            self.github, self.git, self.policy, runner, self.state, SCANNER,
            emit=lambda line: None, dry_run=dry_run, run_id="itest",
            agent_identities=(f"{AGENT_NAME} <{AGENT_EMAIL}>",),
            sleep=lambda _s: None,
        )


class TestRealGit(IntegrationCase):
    def test_the_repository_reads_back_as_expected(self):
        self.assertTrue(self.git.is_repository())
        self.assertEqual(self.git.current_branch(), "main")
        self.assertTrue(self.git.is_clean())
        self.assertEqual(self.git.operation_in_progress(), "")
        self.assertIsNotNone(self.git.rev_parse("refs/remotes/origin/main"))

    def test_an_agent_authored_branch_is_adoptable(self):
        self.repo.make_agent_branch("agent/issue-85-thing")
        audit = self.git.audit_branch(
            "agent/issue-85-thing", "refs/remotes/origin/main", 20, False,
            (f"{AGENT_NAME} <{AGENT_EMAIL}>",), True,
        )
        self.assertTrue(audit.ok, audit.reasons)
        self.assertEqual(audit.commits, 1)

    def test_a_human_authored_branch_is_not_adoptable(self):
        self.repo.make_agent_branch(
            "agent/issue-85-thing", author=HUMAN_NAME, email=HUMAN_EMAIL
        )
        audit = self.git.audit_branch(
            "agent/issue-85-thing", "refs/remotes/origin/main", 20, False,
            (f"{AGENT_NAME} <{AGENT_EMAIL}>",), True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(any("did not make" in r for r in audit.reasons))

    def test_a_branch_that_adds_nothing_is_not_adoptable(self):
        run(["git", "branch", "agent/issue-85-empty", "origin/main"], self.repo.work)
        audit = self.git.audit_branch(
            "agent/issue-85-empty", "refs/remotes/origin/main", 20, False,
            (f"{AGENT_NAME} <{AGENT_EMAIL}>",), True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(any("no commit" in r for r in audit.reasons))

    def test_a_branch_over_the_commit_bound_is_not_adoptable(self):
        self.repo.make_agent_branch("agent/issue-85-big")
        run(["git", "checkout", "--quiet", "agent/issue-85-big"], self.repo.work)
        for index in range(3):
            commit(self.repo.work, f"f{index}.txt", str(index))
        run(["git", "checkout", "--quiet", "main"], self.repo.work)
        audit = self.git.audit_branch(
            "agent/issue-85-big", "refs/remotes/origin/main", 2, False,
            (f"{AGENT_NAME} <{AGENT_EMAIL}>",), True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(any("the limit is" in r for r in audit.reasons))

    def test_a_branch_from_an_unrelated_history_is_not_adoptable(self):
        run(["git", "checkout", "--quiet", "--orphan", "agent/issue-85-alien"],
            self.repo.work)
        run(["git", "rm", "-rq", "--cached", "."], self.repo.work)
        commit(self.repo.work, "alien.txt", "x")
        # An orphan branch leaves the files of the old branch untracked, so
        # the return needs -f.
        run(["git", "checkout", "--quiet", "-f", "main"], self.repo.work)
        audit = self.git.audit_branch(
            "agent/issue-85-alien", "refs/remotes/origin/main", 20, False,
            (f"{AGENT_NAME} <{AGENT_EMAIL}>",), True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(any("shares no history" in r for r in audit.reasons))

    def test_branches_for_issue_finds_any_slug(self):
        self.repo.make_agent_branch("agent/issue-85-homepage-eligibility")
        self.assertEqual(
            self.git.branches_for_issue("agent/", 85),
            ["agent/issue-85-homepage-eligibility"],
        )
        self.assertEqual(self.git.branches_for_issue("agent/", 86), [])

    def test_a_push_outside_the_agent_namespace_is_refused(self):
        with self.assertRaises(GitError):
            self.git.push_branch("main", "agent/")
        with self.assertRaises(GitError):
            self.git.push_branch("feature/x", "agent/")

    def test_push_reaches_the_remote_and_refuses_a_rewrite(self):
        self.repo.make_agent_branch("agent/issue-85-thing")
        self.git.push_branch("agent/issue-85-thing", "agent/")
        self.assertIn(
            "agent/issue-85-thing",
            run(["git", "branch", "--list"], self.repo.remote)
            + run(["git", "for-each-ref", "--format=%(refname:short)"],
                  self.repo.remote),
        )
        # Rewrite the branch so the next push is not a fast forward.
        run(["git", "checkout", "--quiet", "-B", "agent/issue-85-thing",
             "origin/main"], self.repo.work)
        commit(self.repo.work, "src/other.mjs", "different\n")
        run(["git", "checkout", "--quiet", "main"], self.repo.work)
        with self.assertRaises(GitError):
            self.git.push_branch("agent/issue-85-thing", "agent/")

    def test_a_credential_in_a_real_diff_is_found(self):
        self.repo.make_agent_branch(
            "agent/issue-85-leak", content="const k = 'AKIA" + "0123456789ABCDEF';\n"
        )
        diff = self.git.diff_text("refs/remotes/origin/main", "agent/issue-85-leak")
        self.assertTrue(scan_text_for_secrets(SCANNER, diff))

    def test_an_ordinary_diff_is_clean(self):
        self.repo.make_agent_branch("agent/issue-85-ok")
        diff = self.git.diff_text("refs/remotes/origin/main", "agent/issue-85-ok")
        self.assertEqual(scan_text_for_secrets(SCANNER, diff), [])

    def test_a_repository_in_the_middle_of_a_merge_is_reported(self):
        self.repo.make_agent_branch("agent/issue-1-a", content="A\n",
                                    path="conflict.txt")
        run(["git", "checkout", "--quiet", "-b", "other", "origin/main"],
            self.repo.work)
        commit(self.repo.work, "conflict.txt", "B\n")
        proc = subprocess.run(["git", "merge", "agent/issue-1-a"],
                              cwd=self.repo.work, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.git.operation_in_progress(), "a merge")
        run(["git", "merge", "--abort"], self.repo.work)


class TestRealDrain(IntegrationCase):
    def test_a_whole_run_pushes_real_commits_and_merges(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        self.github.add_issue(86, "Use the module", labels=(READY,))
        self.github.dependencies[86] = [85]
        runner = CommittingRunner(self.git, self.repo, [
            {"path": "src/a.mjs", "content": "export const a = 1;\n"},
            {"path": "src/b.mjs", "content": "export const b = 2;\n"},
        ])

        original = self.github.check_runs
        self.github.check_runs = lambda sha: [CheckRun("Quality", "completed", "success")]

        report = self.coordinator(runner).run()

        self.assertEqual([r.issue for r in report.results], [85, 86])
        self.assertEqual(report.merged, 2)
        self.assertEqual(report.count(Outcome.SUCCESS), 2)
        remote_refs = run(
            ["git", "for-each-ref", "--format=%(refname:short)"], self.repo.remote
        )
        self.assertIn("agent/issue-85", remote_refs)
        self.assertIn("agent/issue-86", remote_refs)

    def test_an_existing_valid_branch_is_adopted_and_pushed_without_an_agent(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        self.repo.make_agent_branch("agent/issue-85-implement-the-module")
        runner = CommittingRunner(self.git, self.repo)
        self.github.check_runs = lambda sha: [CheckRun("Quality", "completed", "success")]

        result = self.coordinator(runner).process_issue(85)

        self.assertIs(result.outcome, Outcome.SUCCESS)
        self.assertEqual(runner.calls, [])
        self.assertIn(
            "agent/issue-85-implement-the-module",
            run(["git", "for-each-ref", "--format=%(refname:short)"], self.repo.remote),
        )

    def test_a_real_secret_stops_the_queue_before_the_push(self):
        self.github.add_issue(85, "Leaky", labels=(READY,))
        runner = CommittingRunner(
            self.github and self.git, self.repo,
            [{"path": "src/leak.mjs",
              "content": "const key = 'AKIA" + "0123456789ABCDEF';\n"}],
        )
        report = self.coordinator(runner).run()
        self.assertTrue(report.stopped_for_security)
        self.assertNotIn(
            "agent/issue-85",
            run(["git", "for-each-ref", "--format=%(refname:short)"], self.repo.remote),
        )

    def test_a_dry_run_leaves_the_real_repository_untouched(self):
        self.github.add_issue(85, "Implement the module", labels=(READY,))
        before = run(["git", "for-each-ref", "--format=%(refname) %(objectname)"],
                     self.repo.work)
        github = fakes.FakeGitHub(dry_run=True)
        github.add_issue(85, "Implement the module", labels=(READY,))
        self.git.dry_run = True
        runner = CommittingRunner(self.git, self.repo)
        coordinator = Coordinator(
            github, self.git, self.policy, runner, self.state, SCANNER,
            emit=lambda line: None, dry_run=True, run_id="itest",
            agent_identities=(f"{AGENT_NAME} <{AGENT_EMAIL}>",),
            sleep=lambda _s: None,
        )
        verdicts = coordinator.scan()
        self.assertEqual([v.render() for v in verdicts], ["#85 RUNNABLE"])
        after = run(["git", "for-each-ref", "--format=%(refname) %(objectname)"],
                    self.repo.work)
        self.assertEqual(before, after)
        self.assertEqual(github.mutations, [])
        self.assertEqual(self.git.mutations, [])
        self.assertEqual(runner.calls, [])
        self.assertEqual(
            run(["git", "for-each-ref", "--format=%(refname:short)"], self.repo.remote),
            "main",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
