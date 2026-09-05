#!/usr/bin/env python3
"""Deterministic tests for the agentqueue coordinator.

No network, no container, no git. GitHub, git and agentbox are replaced by the
doubles in agentqueue_fakes.py, so every case below runs in milliseconds and
gives the same answer on every machine.

    python3 verify/probes/agentqueue-unit.test.py

verify/85-agentq.sh runs this file, and it fails the module on any error.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import agentqueue_fakes as fakes  # noqa: E402
from agentqueue import claims as claims_mod  # noqa: E402
from agentqueue import ci as ci_mod  # noqa: E402
from agentqueue import policy as policy_mod  # noqa: E402
from agentqueue import prompts  # noqa: E402
from agentqueue.coordinator import Coordinator, SecurityStop  # noqa: E402
from agentqueue.gitops import BranchAudit  # noqa: E402
from agentqueue.model import (  # noqa: E402
    CheckRun,
    Comment,
    Outcome,
    Runnability,
    branch_for_issue,
    check_verdict,
    classify_agentbox_exit,
    extract_agentbox_summary,
)
from agentqueue.schedule import (  # noqa: E402
    DependencyResolver,
    Scheduler,
    find_cycles,
    parse_prose_blockers,
)

READY = "ready-for-agent"
IN_PROGRESS = "agent-in-progress"


def scheduler_for(github, policy, claims=None):
    resolver = DependencyResolver(
        policy.dependencySources, github.blocked_by, github.get_issue
    )
    return Scheduler(policy, resolver, claims)


def verdicts_of(github, policy, claims=None):
    scheduler = scheduler_for(github, policy, claims)
    result = scheduler.evaluate(github.list_issues(policy.issueLabel))
    return {v.issue: v for v in result}, scheduler


def build_coordinator(github, git, policy, runner, tmpdir, dry_run=False, sleep=None):
    return Coordinator(
        github, git, policy, runner, tmpdir,
        os.path.join(_ROOT, "bin", "scan-secrets"),
        emit=lambda line: None, dry_run=dry_run, run_id="testrun",
        agent_identities=(fakes.AGENT_IDENTITY,),
        sleep=sleep or (lambda _s: None),
    )


# ---------------------------------------------------------------- selection --


class TestSelection(unittest.TestCase):
    def test_selects_ready_for_agent_issues(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "one", labels=(READY,))
        github.add_issue(2, "two", labels=(READY,))
        policy = fakes.make_policy()
        verdicts, _ = verdicts_of(github, policy)
        self.assertEqual(sorted(verdicts), [1, 2])
        self.assertTrue(all(v.runnability is Runnability.RUNNABLE
                            for v in verdicts.values()))

    def test_ignores_other_open_issues(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "labelled", labels=(READY,))
        github.add_issue(2, "unlabelled")
        github.add_issue(3, "other label", labels=("bug",))
        policy = fakes.make_policy()
        verdicts, _ = verdicts_of(github, policy)
        self.assertEqual(list(verdicts), [1])

    def test_ignores_a_closed_issue_that_still_carries_the_label(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "done", state="closed", labels=(READY,))
        policy = fakes.make_policy()
        verdicts, _ = verdicts_of(github, policy)
        self.assertEqual(verdicts, {})

    def test_an_issue_marked_for_a_human_is_not_runnable(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "x", labels=(READY, "ready-for-human"))
        policy = fakes.make_policy()
        verdicts, _ = verdicts_of(github, policy)
        self.assertIs(verdicts[1].runnability, Runnability.NEEDS_HUMAN)


# -------------------------------------------------------------- dependencies --


class TestDependencies(unittest.TestCase):
    def test_open_blocker_blocks(self):
        github = fakes.FakeGitHub()
        github.add_issue(85, "base", labels=(READY,))
        github.add_issue(86, "dependent", labels=(READY,))
        github.dependencies[86] = [85]
        verdicts, _ = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[85].runnability, Runnability.RUNNABLE)
        self.assertIs(verdicts[86].runnability, Runnability.BLOCKED)
        self.assertEqual(verdicts[86].blockers, (85,))

    def test_closed_blocker_is_satisfied(self):
        github = fakes.FakeGitHub()
        github.add_issue(85, "base", state="closed")
        github.add_issue(86, "dependent", labels=(READY,))
        github.dependencies[86] = [85]
        verdicts, _ = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[86].runnability, Runnability.RUNNABLE)

    def test_the_dkkb_shape_orders_correctly(self):
        """#86 and #87 wait for #85. This is the scenario the queue was built for."""
        github = fakes.FakeGitHub()
        github.add_issue(85, "Implement homepage-eligibility module", labels=(READY,))
        github.add_issue(86, "Implement entry-selection module",
                         body='Blocked by "Implement homepage-eligibility module".',
                         labels=(READY,))
        github.add_issue(87, "Implement validate-content split",
                         body='Blocked by "Implement homepage-eligibility module".',
                         labels=(READY,))
        github.dependencies[86] = [85]
        github.dependencies[87] = [85]
        verdicts, scheduler = verdicts_of(github, fakes.make_policy())
        self.assertEqual(
            [verdicts[n].render() for n in (85, 86, 87)],
            ["#85 RUNNABLE", "#86 BLOCKED by #85", "#87 BLOCKED by #85"],
        )
        self.assertEqual(Scheduler.order(list(verdicts.values())), [85])

    def test_prose_fallback_reads_a_numbered_blocker(self):
        github = fakes.FakeGitHub()
        github.native_dependencies = False
        github.add_issue(85, "base", labels=(READY,))
        github.add_issue(86, "dependent", body="Blocked by #85.", labels=(READY,))
        verdicts, _ = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[86].runnability, Runnability.BLOCKED)
        self.assertEqual(verdicts[86].blockers, (85,))

    def test_prose_without_a_number_fails_closed(self):
        github = fakes.FakeGitHub()
        github.native_dependencies = False
        github.add_issue(86, "dependent", body='Blocked by "the other thing".',
                         labels=(READY,))
        verdicts, _ = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[86].runnability, Runnability.AMBIGUOUS)

    def test_native_metadata_settles_an_unnumbered_prose_statement(self):
        """The real dkkb bodies name a blocker by title, not by number."""
        github = fakes.FakeGitHub()
        github.add_issue(85, "base", state="closed")
        github.add_issue(86, "dependent", body='Blocked by "base".', labels=(READY,))
        github.dependencies[86] = [85]
        verdicts, _ = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[86].runnability, Runnability.RUNNABLE)

    def test_a_cross_repository_blocker_is_ambiguous(self):
        blockers = parse_prose_blockers("Blocked by other/repo#12")
        self.assertTrue(blockers.ambiguous)
        self.assertEqual(blockers.numbers, ())

    def test_a_code_fence_is_not_a_dependency_statement(self):
        blockers = parse_prose_blockers("```\nBlocked by #99\n```\nplain text")
        self.assertEqual(blockers.numbers, ())
        self.assertFalse(blockers.ambiguous)

    def test_a_dependency_api_error_fails_closed(self):
        def explode(_number):
            raise RuntimeError("the API is down")

        github = fakes.FakeGitHub()
        github.add_issue(1, "x", labels=(READY,))
        policy = fakes.make_policy()
        resolver = DependencyResolver(("github",), explode, github.get_issue)
        scheduler = Scheduler(policy, resolver, None)
        verdict = scheduler.evaluate(github.list_issues(READY))[0]
        self.assertIs(verdict.runnability, Runnability.AMBIGUOUS)

    def test_dependency_cycle_is_reported_and_never_runs(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "a", labels=(READY,))
        github.add_issue(2, "b", labels=(READY,))
        github.dependencies[1] = [2]
        github.dependencies[2] = [1]
        verdicts, scheduler = verdicts_of(github, fakes.make_policy())
        self.assertIs(verdicts[1].runnability, Runnability.CYCLE)
        self.assertIs(verdicts[2].runnability, Runnability.CYCLE)
        self.assertEqual(len(scheduler.cycles), 1)
        self.assertEqual(Scheduler.order(list(verdicts.values())), [])

    def test_find_cycles_handles_a_long_ring_and_a_self_edge(self):
        self.assertEqual(find_cycles({1: [1]}), [[1]])
        self.assertEqual(len(find_cycles({1: [2], 2: [3], 3: [4], 4: [2]})), 1)
        self.assertEqual(find_cycles({1: [2], 2: []}), [])


# --------------------------------------------------------------------- claims --


class TestClaims(unittest.TestCase):
    def _claim(self, run_id, epoch, issue=1):
        return claims_mod.Claim(
            run_id=run_id, issue=issue, branch="agent/issue-1", base_commit="abc",
            started_at="2026-01-01T00:00:00Z", started_epoch=epoch, host="h",
            coordinator="agentqueue", timeout_seconds=3600,
        )

    def test_a_live_claim_stops_the_scheduler(self):
        github = fakes.FakeGitHub()
        issue = github.add_issue(1, "x", labels=(READY,))
        import time

        github.comments[1] = [
            Comment(1, claims_mod.claim_body(self._claim("r1", int(time.time()))))
        ]
        policy = fakes.make_policy()
        store = claims_mod.ClaimStore(github, policy, "agentqueue")
        verdicts, _ = verdicts_of(github, policy, store)
        self.assertIs(verdicts[1].runnability, Runnability.CLAIMED)

    def test_a_stale_claim_does_not_stop_the_scheduler(self):
        github = fakes.FakeGitHub()
        github.add_issue(1, "x", labels=(READY,))
        github.comments[1] = [Comment(1, claims_mod.claim_body(self._claim("r1", 1)))]
        policy = fakes.make_policy()
        store = claims_mod.ClaimStore(github, policy, "agentqueue")
        verdicts, _ = verdicts_of(github, policy, store)
        self.assertIs(verdicts[1].runnability, Runnability.RUNNABLE)
        self.assertEqual(len(store.stale_for(github.get_issue(1))), 1)

    def test_a_released_claim_is_not_live(self):
        import time

        body = claims_mod.claim_body(self._claim("r1", int(time.time())))
        release = claims_mod.release_body("r1", 1, "SUCCESS", "merged")
        live = claims_mod.live_claims([Comment(1, body), Comment(2, release)], 7200)
        self.assertEqual(live, [])

    def test_the_oldest_live_claim_wins(self):
        import time

        now = int(time.time())
        first = Comment(10, claims_mod.claim_body(self._claim("first", now)))
        second = Comment(11, claims_mod.claim_body(self._claim("second", now)))
        live = claims_mod.live_claims([second, first], 7200)
        self.assertEqual([c.run_id for c in live], ["first", "second"])

    def test_a_losing_coordinator_removes_its_own_comment(self):
        import time

        github = fakes.FakeGitHub()
        issue = github.add_issue(1, "x", labels=(READY,))
        github.comments[1] = [
            Comment(10, claims_mod.claim_body(self._claim("winner", int(time.time()))))
        ]
        policy = fakes.make_policy()
        store = claims_mod.ClaimStore(github, policy, "agentqueue")
        mine = self._claim("mine", int(time.time()))
        winner = store.acquire(issue, mine)
        self.assertIsNotNone(winner)
        self.assertEqual(winner.run_id, "winner")
        bodies = [c.body for c in github.list_comments(1)]
        self.assertEqual(sum("agentqueue:claim" in b for b in bodies), 1)

    def test_the_local_lock_refuses_a_second_holder(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = claims_mod.LocalLock(tmp, "k", 600)
            first.acquire()
            second = claims_mod.LocalLock(tmp, "k", 600)
            with self.assertRaises(claims_mod.LocalLockError):
                second.acquire()
            first.release()
            second.acquire()
            second.release()


# ------------------------------------------------------------------ branches --


class TestBranchesAndAdoption(unittest.TestCase):
    def setUp(self):
        self.github = fakes.FakeGitHub()
        self.github.add_issue(85, "Implement homepage-eligibility module",
                              labels=(READY,))
        self.git = fakes.FakeGit()
        self.policy = fakes.make_policy()

    def _coordinator(self, tmp, runner=None):
        return build_coordinator(
            self.github, self.git, self.policy,
            runner or fakes.FakeRunner(self.git), tmp,
        )

    def test_the_generated_branch_name_is_deterministic(self):
        self.assertEqual(
            branch_for_issue("agent/", 85, "Implement homepage-eligibility module"),
            "agent/issue-85-implement-homepage-eligibility-module",
        )
        self.assertEqual(branch_for_issue("agent/", 9, "!!!"), "agent/issue-9")

    def test_an_existing_branch_with_another_slug_is_found(self):
        self.git.refs["refs/heads/agent/issue-85-homepage-eligibility"] = "s1"
        with tempfile.TemporaryDirectory() as tmp:
            branch, note = self._coordinator(tmp)._branch_for(self.github.get_issue(85))
        self.assertEqual(branch, "agent/issue-85-homepage-eligibility")
        self.assertIn("existing branch", note)

    def test_two_matching_branches_refuse_to_be_guessed(self):
        self.git.refs["refs/heads/agent/issue-85-a"] = "s1"
        self.git.refs["refs/heads/agent/issue-85-b"] = "s2"
        with tempfile.TemporaryDirectory() as tmp:
            branch, note = self._coordinator(tmp)._branch_for(self.github.get_issue(85))
        self.assertEqual(branch, "")
        self.assertIn("more than one branch", note)

    def test_a_valid_existing_branch_is_adopted_without_a_new_agent_run(self):
        branch = "agent/issue-85-homepage-eligibility"
        self.git.refs[f"refs/heads/{branch}"] = "goodsha"
        self.git.audits[branch] = BranchAudit(branch, "goodsha", 1, True, ())
        runner = fakes.FakeRunner(self.git)
        self.policy.autoMerge = False
        self.github.checks["goodsha"] = [CheckRun("Quality", "completed", "success")]
        self.github.head_sha_source = lambda b: self.git.refs[f"refs/heads/{b}"]
        with tempfile.TemporaryDirectory() as tmp:
            result = self._coordinator(tmp, runner).process_issue(85)
        self.assertEqual(runner.calls, [])
        self.assertIs(result.outcome, Outcome.SUCCESS)
        self.assertIn(branch, self.git.pushed)

    def test_an_invalid_existing_branch_is_never_adopted(self):
        branch = "agent/issue-85-homepage-eligibility"
        self.git.refs[f"refs/heads/{branch}"] = "badsha"
        self.git.audits[branch] = BranchAudit(
            branch, "badsha", 1, False,
            ("the branch carries commits that agentbox did not make: Someone <s@e>",),
        )
        runner = fakes.FakeRunner(self.git)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._coordinator(tmp, runner).process_issue(85)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertEqual(runner.calls, [])
        self.assertEqual(self.git.pushed, [])
        self.assertIn("ready-for-human", self.github.get_issue(85).labels)

    def test_the_real_audit_rejects_a_foreign_author(self):
        from agentqueue.gitops import Git

        with tempfile.TemporaryDirectory() as tmp:
            audit = Git.audit_branch(
                _StubGit(tmp), "agent/x", "origin/main", 20, False,
                (fakes.AGENT_IDENTITY,), True,
            )
        self.assertFalse(audit.ok)
        self.assertTrue(any("did not make" in r for r in audit.reasons))


class _StubGit:
    """The smallest object Git.audit_branch needs, with one foreign commit."""

    def __init__(self, root):
        self.root = root

    def rev_parse(self, ref):
        return "tip" if ref != "origin/main" else "base"

    def merge_base(self, a, b):
        return "base"

    def is_ancestor(self, a, b):
        return True

    def commits_between(self, base, tip):
        return 1

    def merges_between(self, base, tip):
        return 0

    def authors_between(self, base, tip):
        return ["Mallory <m@example.invalid>"]

    def current_branch(self):
        return "main"


# ------------------------------------------------------------------ CI logic --


class TestChecks(unittest.TestCase):
    def test_all_green_passes(self):
        verdict = check_verdict([CheckRun("A", "completed", "success")], [], True)
        self.assertEqual(verdict["state"], "passed")

    def test_a_failure_fails(self):
        verdict = check_verdict(
            [CheckRun("A", "completed", "success"),
             CheckRun("B", "completed", "failure")], [], True,
        )
        self.assertEqual(verdict["state"], "failed")
        self.assertEqual(verdict["failed"], ["B"])

    def test_skipped_and_neutral_are_not_failures(self):
        verdict = check_verdict(
            [CheckRun("A", "completed", "skipped"),
             CheckRun("B", "completed", "neutral")], [], True,
        )
        self.assertEqual(verdict["state"], "passed")

    def test_no_check_at_all_is_not_a_pass(self):
        self.assertEqual(check_verdict([], [], True)["state"], "none")
        self.assertEqual(check_verdict([], [], False)["state"], "passed")

    def test_a_missing_required_check_is_not_a_pass(self):
        verdict = check_verdict(
            [CheckRun("A", "completed", "success")], ["A", "Quality"], True
        )
        self.assertEqual(verdict["state"], "missing")

    def test_wait_returns_when_the_checks_settle(self):
        github = fakes.FakeGitHub()
        states = [
            [CheckRun("Quality", "in_progress")],
            [CheckRun("Quality", "completed", "success")],
        ]
        github.check_runs = lambda sha: states.pop(0) if states else states
        policy = fakes.make_policy(ciPollSeconds=1, ciTimeoutSeconds=60)
        clock = iter([0, 0, 1, 1, 2, 2, 3, 3])
        result = ci_mod.wait_for_checks(
            github, "sha", policy, sleep=lambda _s: None, clock=lambda: next(clock)
        )
        self.assertTrue(result.passed)

    def test_wait_gives_up_after_the_timeout(self):
        github = fakes.FakeGitHub()
        github.check_runs = lambda sha: [CheckRun("Quality", "in_progress")]
        policy = fakes.make_policy(ciPollSeconds=1, ciTimeoutSeconds=5)
        ticks = iter([0, 1, 2, 3, 4, 5, 6, 7, 8])
        result = ci_mod.wait_for_checks(
            github, "sha", policy, sleep=lambda _s: None, clock=lambda: next(ticks)
        )
        self.assertEqual(result.state, "timeout")


# -------------------------------------------------------- agentbox decoding --


class TestAgentboxDecoding(unittest.TestCase):
    def test_a_product_refusal_belongs_to_the_issue(self):
        self.assertIs(
            classify_agentbox_exit(9, "agentbox: the agent produced no commit on x"),
            Outcome.FAILED_FINAL,
        )

    def test_an_unrecognised_refusal_stops_the_queue(self):
        self.assertIs(
            classify_agentbox_exit(9, "agentbox: something nobody has seen"),
            Outcome.SECURITY_OR_INTEGRITY_FAILURE,
        )

    def test_an_isolation_failure_stops_the_queue_whatever_the_exit_code(self):
        self.assertIs(
            classify_agentbox_exit(8, "an isolation probe failed; the sandbox is not safe"),
            Outcome.SECURITY_OR_INTEGRITY_FAILURE,
        )

    def test_a_timeout_is_transient(self):
        self.assertIs(classify_agentbox_exit(10, ""), Outcome.FAILED_TRANSIENT)

    def test_a_held_branch_is_blocked(self):
        self.assertIs(classify_agentbox_exit(11, ""), Outcome.BLOCKED)

    def test_the_summary_block_is_read(self):
        text = (
            "noise\n===AGENTBOX_SUMMARY_JSON===\n"
            '{"checksPassed": true}\n===END===\ntrailing\n'
        )
        self.assertEqual(extract_agentbox_summary(text), {"checksPassed": True})
        self.assertIsNone(extract_agentbox_summary("no block here"))


# ------------------------------------------------------------- the lifecycle --


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.github = fakes.FakeGitHub()
        self.git = fakes.FakeGit()
        self.github.head_sha_source = lambda b: self.git.refs[f"refs/heads/{b}"]
        self.policy = fakes.make_policy(
            autoMerge=True, mergeWithoutReview=True, checks=("pnpm check",),
            requiredChecks=("Quality",),
        )

    def _green(self, sha):
        self.github.checks[sha] = [CheckRun("Quality", "completed", "success")]

    def _red(self, sha, log="the test failed"):
        self.github.checks[sha] = [CheckRun("Quality", "completed", "failure")]
        self.github.logs[sha] = log

    def test_green_ci_merges_and_closes(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        self._green("s1")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.SUCCESS)
        self.assertTrue(result.merged)
        self.assertEqual(len(self.github.merge_calls), 1)
        self.assertFalse(self.github.get_issue(1).is_open)

    def test_ci_failure_then_repair_then_merge(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}, {"sha": "s2"}])
        self._red("s1", "AssertionError: expected 1")
        self._green("s2")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.SUCCESS)
        self.assertTrue(result.merged)
        self.assertEqual(result.ci_retries, 1)
        self.assertEqual(len(runner.calls), 2)
        self.assertTrue(runner.calls[1]["continuation"])
        self.assertIn("AssertionError", runner.calls[1]["prompt"])

    def test_retry_exhaustion_asks_for_a_human_and_never_merges(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        self.policy.maxRetries = 1
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}, {"sha": "s2"}])
        self._red("s1")
        self._red("s2")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertFalse(result.merged)
        self.assertEqual(self.github.merge_calls, [])
        self.assertIn("ready-for-human", self.github.get_issue(1).labels)

    def test_a_failing_local_check_is_repaired_before_anything_is_pushed(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [
            {"sha": "s1", "checks_passed": False,
             "failed_checks": [{"command": "pnpm check", "exitCode": 1,
                                "tail": "type error"}]},
            {"sha": "s2", "checks_passed": True},
        ])
        self._green("s2")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.SUCCESS)
        self.assertEqual(self.git.pushed, ["agent/issue-1-do-the-thing"])
        self.assertIn("type error", runner.calls[1]["prompt"])

    def test_local_checks_that_never_pass_are_never_pushed(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        self.policy.maxRetries = 1
        failing = {"sha": "s1", "checks_passed": False,
                   "failed_checks": [{"command": "pnpm check", "exitCode": 1,
                                      "tail": "boom"}]}
        runner = fakes.FakeRunner(self.git, [dict(failing), dict(failing, sha="s2")])
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertEqual(self.git.pushed, [])

    def test_an_issue_closed_during_execution_is_not_merged(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        self._green("s1")

        github = self.github
        original = github.get_issue
        git = self.git

        def closing_get_issue(number):
            issue = original(number)
            # Somebody closes the issue while the checks run, which is after
            # the branch is pushed and before the merge gates read it again.
            if git.pushed and issue.is_open:
                github.issues[number] = type(issue)(
                    issue.number, issue.title, issue.body, "closed",
                    issue.labels, issue.url,
                )
            return github.issues[number]

        github.get_issue = closing_get_issue
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIn(result.outcome, (Outcome.BLOCKED, Outcome.NEEDS_HUMAN))
        self.assertEqual(github.merge_calls, [])

    def test_a_moved_pull_request_head_refuses_the_merge(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        self._green("s1")

        real_get_pull = self.github.get_pull

        def moved(number):
            pull = real_get_pull(number)
            return type(pull)(
                pull.number, pull.state, pull.head_ref, pull.base_ref,
                "somebody-else-pushed", pull.merged, pull.mergeable,
                pull.merge_state_status, pull.url,
            )

        self.github.get_pull = moved
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("head", result.detail)
        self.assertEqual(self.github.merge_calls, [])

    def test_a_merge_conflict_refuses_the_merge(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        self._green("s1")
        real_get_pull = self.github.get_pull

        def conflicting(number):
            pull = real_get_pull(number)
            return type(pull)(
                pull.number, pull.state, pull.head_ref, pull.base_ref,
                pull.head_sha, pull.merged, "CONFLICTING", "DIRTY", pull.url,
            )

        self.github.get_pull = conflicting
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("conflict", result.detail)
        self.assertEqual(self.github.merge_calls, [])

    def test_an_open_pull_request_is_adopted_not_duplicated(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        branch = "agent/issue-1-do-the-thing"
        self.git.refs[f"refs/heads/{branch}"] = "s1"
        self.git.audits[branch] = BranchAudit(branch, "s1", 1, True, ())
        from agentqueue.model import PullRequest

        self.github.pulls[7] = PullRequest(
            7, "OPEN", branch, "main", "s1", False, "MERGEABLE", "CLEAN", "u"
        )
        self._green("s1")
        runner = fakes.FakeRunner(self.git)
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertEqual(result.pull_request, 7)
        self.assertEqual(len(self.github.pulls), 1)

    def test_a_merged_pull_request_with_an_open_issue_asks_for_a_human(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        branch = "agent/issue-1-do-the-thing"
        self.git.refs[f"refs/heads/{branch}"] = "s1"
        self.git.audits[branch] = BranchAudit(branch, "s1", 1, True, ())
        from agentqueue.model import PullRequest

        self.github.pulls[7] = PullRequest(
            7, "MERGED", branch, "main", "s1", True, "MERGEABLE", "CLEAN", "u"
        )
        runner = fakes.FakeRunner(self.git)
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("already", result.detail)

    def test_a_review_gate_can_refuse_a_merge(self):
        self.github.add_issue(1, "Do the thing", labels=(READY,))
        self.policy.reviewPolicy = "required"
        self.policy.mergeWithoutReview = False
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        self._green("s1")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).process_issue(1)
        self.assertIs(result.outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("independent review", result.detail)
        self.assertEqual(self.github.merge_calls, [])


# ---------------------------------------------------------------- the run loop --


class TestDrain(unittest.TestCase):
    def setUp(self):
        self.github = fakes.FakeGitHub()
        self.git = fakes.FakeGit()
        self.github.head_sha_source = lambda b: self.git.refs[f"refs/heads/{b}"]
        self.policy = fakes.make_policy(
            autoMerge=True, mergeWithoutReview=True, checks=("pnpm check",)
        )

    def test_a_merge_unblocks_the_next_issue(self):
        self.github.add_issue(85, "base work", labels=(READY,))
        self.github.add_issue(86, "dependent work", labels=(READY,))
        self.github.dependencies[86] = [85]
        runner = fakes.FakeRunner(self.git, [{"sha": "s85"}, {"sha": "s86"}])
        self.github.checks["s85"] = [CheckRun("Quality", "completed", "success")]
        self.github.checks["s86"] = [CheckRun("Quality", "completed", "success")]
        with tempfile.TemporaryDirectory() as tmp:
            report = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).run()
        self.assertEqual([r.issue for r in report.results], [85, 86])
        self.assertEqual(report.merged, 2)
        self.assertGreaterEqual(report.waves, 2)

    def test_one_broken_issue_does_not_stop_the_queue(self):
        self.github.add_issue(1, "broken", labels=(READY,))
        self.github.add_issue(2, "fine", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [
            {"exit": 8, "output": "the agent gave up"},
            {"sha": "s2"},
        ])
        self.github.checks["s2"] = [CheckRun("Quality", "completed", "success")]
        with tempfile.TemporaryDirectory() as tmp:
            report = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).run()
        outcomes = {r.issue: r.outcome for r in report.results}
        self.assertIs(outcomes[1], Outcome.FAILED_TRANSIENT)
        self.assertIs(outcomes[2], Outcome.SUCCESS)
        self.assertEqual(report.merged, 1)
        self.assertFalse(report.stopped_for_security)

    def test_a_security_failure_stops_the_whole_queue(self):
        self.github.add_issue(1, "first", labels=(READY,))
        self.github.add_issue(2, "second", labels=(READY,))
        runner = fakes.FakeRunner(self.git, [
            {"exit": 9, "output": "DISPOSABLE CLONE INTEGRITY FAILED: 3 change(s)"},
            {"sha": "s2"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            report = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).run()
        self.assertTrue(report.stopped_for_security)
        self.assertEqual([r.issue for r in report.results], [1])
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(self.git.pushed, [])

    def test_a_credential_in_the_diff_stops_the_whole_queue(self):
        self.github.add_issue(1, "leaky", labels=(READY,))
        self.git.diffs["agent/issue-1-leaky"] = (
            "+AKIA" + "0123456789ABCDEF\n"
        )
        runner = fakes.FakeRunner(self.git, [{"sha": "s1"}])
        with tempfile.TemporaryDirectory() as tmp:
            report = build_coordinator(
                self.github, self.git, self.policy, runner, tmp
            ).run()
        self.assertTrue(report.stopped_for_security)
        self.assertEqual(self.git.pushed, [])

    def test_an_empty_queue_finishes_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = build_coordinator(
                self.github, self.git, self.policy, fakes.FakeRunner(self.git), tmp
            ).run()
        self.assertEqual(report.results, [])
        self.assertEqual(report.merged, 0)


# -------------------------------------------------------------------- dry run --


class TestDryRun(unittest.TestCase):
    def test_a_dry_run_changes_nothing(self):
        github = fakes.FakeGitHub(dry_run=True)
        github.add_issue(85, "base", labels=(READY,))
        github.add_issue(86, "dependent", labels=(READY,))
        github.dependencies[86] = [85]
        git = fakes.FakeGit()
        git.dry_run = True
        policy = fakes.make_policy()
        runner = fakes.FakeRunner(git)
        runner.dry_run = True
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = build_coordinator(github, git, policy, runner, tmp,
                                            dry_run=True)
            verdicts = coordinator.scan()
        self.assertEqual([v.render() for v in verdicts],
                         ["#85 RUNNABLE", "#86 BLOCKED by #85"])
        self.assertEqual(github.mutations, [])
        self.assertEqual(git.mutations, [])
        self.assertEqual(runner.calls, [])

    def test_the_dry_run_client_refuses_a_mutation(self):
        from agentqueue.ghapi import DryRunViolation

        github = fakes.FakeGitHub(dry_run=True)
        github.add_issue(1, "x", labels=(READY,))
        with self.assertRaises(DryRunViolation):
            github.add_label(1, "anything")


# --------------------------------------------------------------------- policy --


class TestPolicy(unittest.TestCase):
    def test_the_shipped_default_is_valid(self):
        fakes.make_policy()

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(policy_mod.PolicyError):
            policy_mod.overlay(policy_mod.Policy(), {"autoMerg": True}, "test")

    def test_merge_without_review_is_an_explicit_choice(self):
        self.assertFalse(fakes.make_policy().merge_is_permitted_without_review())
        self.assertTrue(
            fakes.make_policy(mergeWithoutReview=True)
            .merge_is_permitted_without_review()
        )
        self.assertTrue(
            fakes.make_policy(reviewPolicy="none").merge_is_permitted_without_review()
        )

    def test_a_contradictory_review_policy_is_refused(self):
        with self.assertRaises(policy_mod.PolicyError):
            fakes.make_policy(reviewPolicy="required", mergeWithoutReview=True)

    def test_duplicate_lifecycle_labels_are_refused(self):
        with self.assertRaises(policy_mod.PolicyError):
            fakes.make_policy(humanLabel="ready-for-agent")

    def test_a_repository_policy_overlays_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".agentqueue.json"), "w") as handle:
                handle.write('{"autoMerge": true, "checks": ["pnpm check"]}')
            pol = policy_mod.load(
                tmp,
                os.path.join(_ROOT, "config", "agentqueue", "policy.default.json"),
            )
        self.assertTrue(pol.autoMerge)
        self.assertEqual(pol.checks, ("pnpm check",))
        self.assertEqual(len(pol.sources), 2)


# -------------------------------------------------------------------- prompts --


class TestPrompts(unittest.TestCase):
    def test_the_prompt_carries_the_issue_and_the_checks(self):
        issue = fakes.FakeGitHub().add_issue(
            42, "Add a widget", "Do the thing.\n\n## Acceptance\n\n- [ ] it works\n",
            labels=(READY,),
        )
        text = prompts.implementation_prompt(issue, [], [], "a" * 40, ["pnpm check"])
        self.assertIn("issue #42", text)
        self.assertIn("Do the thing.", text)
        self.assertIn("pnpm check", text)
        self.assertIn("it works", text)
        self.assertIn("Do not push", text)

    def test_the_prompt_never_carries_a_credential_path(self):
        issue = fakes.FakeGitHub().add_issue(1, "t", "b", labels=(READY,))
        text = prompts.implementation_prompt(issue, [], [], "a" * 40, [])
        for forbidden in ("secrets.env", "CLAUDE_CODE_OAUTH_TOKEN",
                          "OPENAI_API_KEY", "/creds/"):
            self.assertNotIn(forbidden, text)

    def test_the_pull_request_body_does_not_claim_a_review_that_did_not_run(self):
        issue = fakes.FakeGitHub().add_issue(5, "t", "b", labels=(READY,))
        body = prompts.pull_request_body(
            issue, "run1", "b" * 40, ["pnpm check"], True,
            {"ran": False, "reason": "no credential"}, 0,
        )
        self.assertIn("Closes #5", body)
        self.assertIn("No independent model review ran", body)
        self.assertNotIn("secrets.env", body)

    def test_a_failing_check_is_reported_as_failing(self):
        issue = fakes.FakeGitHub().add_issue(5, "t", "b", labels=(READY,))
        body = prompts.pull_request_body(
            issue, "run1", "b" * 40, ["pnpm check"], False, {"ran": True}, 1
        )
        self.assertIn("FAILED", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
