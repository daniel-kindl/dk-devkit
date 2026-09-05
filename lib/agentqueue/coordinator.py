"""The drain loop: select an issue, implement it, merge it, look again.

    scan the backlog
      -> compute runnable
      -> claim one issue
      -> adopt existing work, or run agentbox
      -> repair inside the budget while a check fails
      -> scan the diff for a credential
      -> push the validated branch
      -> open or adopt the pull request
      -> wait for the GitHub checks
      -> repair inside the budget while a check fails
      -> re-check every merge gate
      -> merge
      -> rescan, because a merge can unblock another issue

The rescan is not an optimisation. #86 and #87 only become runnable when #85
merges, and a queue that scanned once would stop with work left.

One rule governs every refusal in this file: the queue never merges on
uncertainty. A gate that cannot be answered is a gate that failed.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime
import os
import socket
import time
from typing import Callable, Dict, List, Optional, Sequence

from . import claims as claims_mod
from . import ci as ci_mod
from . import prompts
from .model import (
    Issue,
    IssueResult,
    Outcome,
    Runnability,
    Verdict,
    branch_for_issue,
)
from .schedule import DependencyResolver, Scheduler


class IssueRefused(Exception):
    """This issue cannot go on. The queue continues with another one."""

    def __init__(self, outcome, detail: str):
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


class SecurityStop(Exception):
    """A security or integrity failure. The whole queue stops at once."""

    def __init__(self, issue: int, detail: str):
        super().__init__(detail)
        self.issue = issue
        self.detail = detail


@dataclasses.dataclass
class Report:
    started: float = dataclasses.field(default_factory=time.time)
    results: List[IssueResult] = dataclasses.field(default_factory=list)
    verdicts: List[Verdict] = dataclasses.field(default_factory=list)
    cycles: List[List[int]] = dataclasses.field(default_factory=list)
    reclaimed: List[str] = dataclasses.field(default_factory=list)
    stopped_for_security: str = ""
    waves: int = 0

    @property
    def elapsed_seconds(self) -> int:
        return int(time.time() - self.started)

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.outcome is outcome)

    @property
    def merged(self) -> int:
        return sum(1 for r in self.results if r.merged)

    @property
    def agentbox_runs(self) -> int:
        return sum(r.agentbox_runs for r in self.results)

    @property
    def ci_retries(self) -> int:
        return sum(r.ci_retries for r in self.results)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Coordinator:
    def __init__(
        self,
        github,
        git,
        policy,
        runner,
        state_dir: str,
        scanner: str,
        emit: Callable[[str], None],
        dry_run: bool = False,
        run_id: str = "",
        agent_identities: Sequence[str] = (),
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.github = github
        self.git = git
        self.policy = policy
        self.runner = runner
        self.state_dir = state_dir
        self.scanner = scanner
        self.emit = emit
        self.dry_run = dry_run
        self.run_id = run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.agent_identities = tuple(agent_identities)
        self.sleep = sleep
        self.claims = claims_mod.ClaimStore(
            github, policy, coordinator="agentqueue", dry_run=dry_run
        )
        self.resolver = DependencyResolver(
            policy.dependencySources, github.blocked_by, github.get_issue
        )
        self.scheduler = Scheduler(policy, self.resolver, None if dry_run else self.claims)
        self._processed: List[int] = []

    # ------------------------------------------------------------- scanning --

    def base_ref(self) -> str:
        return f"refs/remotes/origin/{self.policy.baseBranch}"

    def scan(self) -> List[Verdict]:
        """One evaluation of the whole backlog."""
        self.resolver = DependencyResolver(
            self.policy.dependencySources, self.github.blocked_by, self.github.get_issue
        )
        self.scheduler = Scheduler(
            self.policy, self.resolver, None if self.dry_run else self.claims
        )
        candidates = self.github.list_issues(self.policy.issueLabel)
        return self.scheduler.evaluate(candidates)

    # ---------------------------------------------------------------- drain --

    def drain(self, once: bool = False, max_waves: int = 100) -> Report:
        report = Report()
        while report.waves < max_waves:
            report.waves += 1
            verdicts = self.scan()
            report.verdicts = verdicts
            report.cycles = list(getattr(self.scheduler, "cycles", []))

            runnable = [
                v.issue
                for v in verdicts
                if v.runnability is Runnability.RUNNABLE and v.issue not in self._processed
            ]
            if not runnable:
                break

            wave = runnable[: max(1, self.policy.maxParallel)]
            self.emit(
                f"wave {report.waves}: "
                + ", ".join(f"#{n}" for n in wave)
                + f"  (runnable: {len(runnable)})"
            )
            try:
                results = self._run_wave(wave)
            except SecurityStop as stop:
                report.stopped_for_security = f"#{stop.issue}: {stop.detail}"
                report.results.append(
                    IssueResult(stop.issue, Outcome.SECURITY_OR_INTEGRITY_FAILURE,
                                stop.detail)
                )
                break
            report.results.extend(results)
            report.reclaimed.extend(
                f"#{c.issue} run {c.run_id}" for c in self.claims.reclaimed
            )
            self.claims.reclaimed.clear()
            if once:
                break

        # A final scan, so the summary reports the state after the last merge.
        if not report.stopped_for_security:
            report.verdicts = self.scan()
            report.cycles = list(getattr(self.scheduler, "cycles", []))
        return report

    def _run_wave(self, numbers: Sequence[int]) -> List[IssueResult]:
        if len(numbers) == 1 or self.policy.maxParallel <= 1:
            return [self._guarded(n) for n in numbers]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.policy.maxParallel
        ) as pool:
            futures = {pool.submit(self._guarded, n): n for n in numbers}
            out: List[IssueResult] = []
            for future in concurrent.futures.as_completed(futures):
                out.append(future.result())
        return sorted(out, key=lambda r: r.issue)

    def _guarded(self, number: int) -> IssueResult:
        self._processed.append(number)
        try:
            result = self.process_issue(number)
        except SecurityStop:
            raise
        except Exception as exc:  # a coordinator defect must not be silent
            result = IssueResult(number, Outcome.FAILED_FINAL, f"coordinator error: {exc}")
        if result.outcome.stops_queue:
            raise SecurityStop(number, result.detail)
        return result

    # -------------------------------------------------------- one issue --

    def process_issue(self, number: int) -> IssueResult:
        policy = self.policy
        lock = claims_mod.LocalLock(
            os.path.join(self.state_dir, "locks"),
            f"{self.github.owner}--{self.github.name}--issue-{number}",
            policy.agentTimeoutSeconds,
        )
        try:
            lock.acquire()
        except claims_mod.LocalLockError as exc:
            return IssueResult(number, Outcome.BLOCKED, str(exc))

        run_id = f"{self.run_id}-i{number}"
        result = IssueResult(number, Outcome.FAILED_FINAL, "not started")
        claimed = False
        try:
            issue = self.github.get_issue(number)
            recheck = self.scheduler.evaluate([issue])[0]
            if recheck.runnability is not Runnability.RUNNABLE:
                return IssueResult(
                    number, Outcome.BLOCKED,
                    f"no longer runnable: {recheck.render()}",
                )

            branch, branch_note = self._branch_for(issue)
            if not branch:
                return self._needs_human(
                    issue, run_id, "no usable branch name", branch_note
                )

            base_sha = self.git.rev_parse(self.base_ref())
            if not base_sha:
                return IssueResult(
                    number, Outcome.NEEDS_HUMAN,
                    f"cannot resolve {self.base_ref()}",
                )

            claim = claims_mod.Claim(
                run_id=run_id, issue=number, branch=branch, base_commit=base_sha,
                started_at=_utc_now_iso(), started_epoch=int(time.time()),
                host=socket.gethostname(), coordinator="agentqueue",
                timeout_seconds=policy.agentTimeoutSeconds,
            )
            winner = self.claims.acquire(issue, claim)
            if winner is not None:
                return IssueResult(
                    number, Outcome.BLOCKED,
                    f"another coordinator holds the claim (run {winner.run_id})",
                )
            claimed = True
            try:
                result = self._implement_and_deliver(issue, branch, base_sha,
                                                     run_id, branch_note)
            except IssueRefused as refusal:
                result = IssueResult(number, refusal.outcome, refusal.detail,
                                     branch=branch)
                if refusal.outcome is Outcome.NEEDS_HUMAN:
                    self._flag_human(issue, run_id, result)
            return result
        finally:
            if claimed and not self.dry_run:
                try:
                    self.claims.release(
                        number, run_id, result.outcome.value, result.detail
                    )
                except Exception as exc:  # the claim must not outlive the run
                    self.emit(f"    warning: the claim of #{number} was not released: {exc}")
            lock.release()

    # ------------------------------------------------------ the lifecycle --

    def _branch_for(self, issue: Issue):
        prefix = self.policy.branchPrefix
        existing = self.git.branches_for_issue(prefix, issue.number)
        if len(existing) > 1:
            return "", (
                "more than one branch matches this issue: " + ", ".join(existing)
            )
        if existing:
            return existing[0], f"an existing branch is present: {existing[0]}"
        name = branch_for_issue(prefix, issue.number, issue.title)
        if not self.git.check_ref_format(name):
            name = f"{prefix}issue-{issue.number}"
            if not self.git.check_ref_format(name):
                return "", f"git rejects the branch name {name}"
        return name, ""

    def _implement_and_deliver(
        self, issue: Issue, branch: str, base_sha: str, run_id: str, branch_note: str
    ) -> IssueResult:
        policy = self.policy
        result = IssueResult(issue.number, Outcome.FAILED_FINAL, "", branch=branch)
        run_dir = os.path.join(self.state_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)

        blocked = self.git.operation_in_progress()
        if blocked:
            result.outcome = Outcome.NEEDS_HUMAN
            result.detail = f"the repository is in the middle of {blocked}"
            return self._flag_human(issue, run_id, result)

        adopted = ""
        agent_run = None
        audit = None
        if self.git.ref_exists(branch) and policy.adoptExistingBranch:
            audit = self.git.audit_branch(
                branch, self.base_ref(), policy.maxCommits, False,
                self.agent_identities, policy.requireAgentAuthoredCommits,
            )
            if audit.ok:
                adopted = audit.render()
                self.emit(f"    adopting existing work: {adopted}")
            else:
                result.outcome = Outcome.NEEDS_HUMAN
                result.detail = (
                    "an existing branch matches this issue and it cannot be "
                    f"adopted. {audit.render()}"
                )
                return self._flag_human(issue, run_id, result)
        elif self.git.ref_exists(branch):
            result.outcome = Outcome.NEEDS_HUMAN
            result.detail = f"{branch} exists and adoptExistingBranch is off"
            return self._flag_human(issue, run_id, result)

        if not adopted:
            prompt_file = os.path.join(run_dir, "implement.md")
            self._write_prompt(issue, base_sha, prompt_file)
            agent_run = self.runner.run(
                self.git.root, branch, prompt_file, self.base_ref(),
                continuation=False, log_name="implement",
            )
            result.agentbox_runs += 1
            if agent_run.outcome.stops_queue:
                result.outcome = agent_run.outcome
                result.detail = f"agentbox reported an integrity failure (exit {agent_run.exit_code})"
                return result
            if agent_run.outcome is not Outcome.SUCCESS:
                return self._after_failed_agent(issue, run_id, result, agent_run)

        # --- the deterministic checks must be green before anything is pushed
        attempts = 0
        while (
            agent_run is not None
            and agent_run.checks_passed is False
            and attempts < policy.maxRetries
        ):
            attempts += 1
            result.ci_retries += 1
            self.emit(f"    local checks failed; repair attempt {attempts}")
            agent_run = self._repair(
                issue, branch, run_dir, agent_run.failed_checks,
                agent_run.failure_evidence, attempts, run_id,
            )
            result.agentbox_runs += 1
            if agent_run.outcome.stops_queue:
                result.outcome = agent_run.outcome
                result.detail = "agentbox reported an integrity failure during a repair"
                return result

        if agent_run is not None and agent_run.checks_passed is False:
            result.outcome = Outcome.NEEDS_HUMAN
            result.detail = (
                "the deterministic checks still fail after "
                f"{attempts} repair attempt(s): "
                + ", ".join(agent_run.failed_checks)
            )
            return self._flag_human(issue, run_id, result)

        # --- nothing is published before the diff is read -------------------
        self._require_clean_diff(issue, branch, result)

        # --- push, and open or adopt the pull request -----------------------
        self.git.push_branch(branch, policy.branchPrefix)
        head_sha = self.git.rev_parse(branch) or ""
        pull = self._pull_request_for(issue, branch, base_sha, run_id, agent_run, adopted)
        result.pull_request = pull.number
        self.emit(f"    pull request #{pull.number} at {pull.url}")

        # --- the GitHub checks, with a bounded repair loop -------------------
        while True:
            outcome = ci_mod.wait_for_checks(
                self.github, head_sha, policy, sleep=self.sleep, emit=self.emit
            )
            if outcome.passed:
                break
            if outcome.state != "failed" or attempts >= policy.maxRetries:
                result.outcome = Outcome.NEEDS_HUMAN
                result.detail = f"the GitHub checks did not pass: {outcome.render()}"
                return self._flag_human(issue, run_id, result, pull=pull.number)
            attempts += 1
            result.ci_retries += 1
            self.emit(f"    GitHub checks failed; repair attempt {attempts}")
            evidence = self.github.failing_run_log(head_sha)
            agent_run = self._repair(
                issue, branch, run_dir, list(outcome.failed), evidence, attempts, run_id
            )
            result.agentbox_runs += 1
            if agent_run.outcome.stops_queue:
                result.outcome = agent_run.outcome
                result.detail = "agentbox reported an integrity failure during a repair"
                return result
            if agent_run.outcome is not Outcome.SUCCESS:
                result.outcome = Outcome.FAILED_FINAL
                result.detail = f"the repair run failed (exit {agent_run.exit_code})"
                return self._flag_failed(issue, run_id, result, pull=pull.number)
            self._require_clean_diff(issue, branch, result)
            self.git.push_branch(branch, policy.branchPrefix)
            head_sha = self.git.rev_parse(branch) or ""

        # --- the merge gates -------------------------------------------------
        if not policy.autoMerge:
            result.outcome = Outcome.SUCCESS
            result.detail = (
                f"pull request #{pull.number} is green. autoMerge is off, so a "
                "human merges it."
            )
            return result

        gate = self._merge_gates(issue, branch, pull.number, head_sha, agent_run)
        if gate:
            result.outcome = Outcome.NEEDS_HUMAN
            result.detail = "a merge gate refused: " + gate
            return self._flag_human(issue, run_id, result, pull=pull.number)

        self.github.merge_pull(pull.number, policy.mergeMethod, head_sha)
        after = self.github.get_pull(pull.number)
        if not after.merged:
            result.outcome = Outcome.NEEDS_HUMAN
            result.detail = f"the merge call returned, but #{pull.number} is not merged"
            return self._flag_human(issue, run_id, result, pull=pull.number)

        result.merged = True
        result.outcome = Outcome.SUCCESS
        result.detail = f"merged as #{pull.number}"
        self._after_merge(issue, branch, pull.number, result)
        return result

    # ------------------------------------------------------------- helpers --

    def _write_prompt(self, issue: Issue, base_sha: str, path: str) -> None:
        comments = self.github.list_comments(issue.number)
        referenced = []
        if self.policy.referencedIssueDepth > 0:
            for number in prompts.referenced_issues(issue.body, exclude=(issue.number,))[
                : self.policy.maxReferencedIssues
            ]:
                try:
                    other = self.github.get_issue(number)
                except Exception:
                    continue
                referenced.append((other, self.github.list_comments(number)))
        text = prompts.implementation_prompt(
            issue, comments, referenced, base_sha, self.policy.checks,
            self.policy.maxPromptBytes,
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _repair(self, issue, branch, run_dir, failures, evidence, attempt, run_id):
        path = os.path.join(run_dir, f"repair-{attempt}.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                prompts.repair_prompt(
                    issue, branch, failures, evidence, self.policy.checks, attempt
                )
            )
        return self.runner.run(
            self.git.root, branch, path, self.base_ref(),
            continuation=True, log_name=f"repair-{attempt}",
        )

    def _require_clean_diff(self, issue: Issue, branch: str, result: IssueResult) -> None:
        if not self.policy.scanDiffForSecrets:
            return
        diff = self.git.diff_text(self.base_ref(), branch)
        findings = self.gitops_scan(diff)
        if findings:
            raise SecurityStop(
                issue.number,
                "the branch diff matches a credential pattern, so nothing was "
                "pushed: " + "; ".join(findings[:3]),
            )

    def gitops_scan(self, diff: str) -> List[str]:
        from .gitops import scan_text_for_secrets

        return scan_text_for_secrets(self.scanner, diff)

    def _pull_request_for(self, issue, branch, base_sha, run_id, agent_run, adopted):
        body = prompts.pull_request_body(
            issue, run_id, base_sha, self.policy.checks,
            agent_run.checks_passed if agent_run else True,
            agent_run.review if agent_run else {"ran": False, "reason": "adopted work"},
            agent_run.fix_rounds if agent_run else 0,
            adopted,
        )
        existing = None
        if self.policy.adoptExistingPullRequest:
            existing = self.github.find_pull_for_branch(branch)
        if existing and existing.state == "OPEN":
            if existing.base_ref != self.policy.baseBranch:
                raise SecurityStop(
                    issue.number,
                    f"pull request #{existing.number} targets {existing.base_ref}, "
                    f"not {self.policy.baseBranch}",
                )
            self.github.update_pull_body(existing.number, body)
            return self.github.get_pull(existing.number)
        if existing and existing.state in ("MERGED", "CLOSED"):
            # The work reached the base branch, and the issue did not close.
            # Guessing which of the two is wrong is exactly what a coordinator
            # must not do.
            raise IssueRefused(
                Outcome.NEEDS_HUMAN,
                f"pull request #{existing.number} for {branch} is already "
                f"{existing.state}, and the issue is still open",
            )
        return self.github.create_pull(
            prompts.pull_request_title(issue), body, branch, self.policy.baseBranch
        )

    def _merge_gates(self, issue, branch, pull_number, head_sha, agent_run) -> str:
        """Return the first gate that refuses, or an empty string."""
        policy = self.policy
        fresh = self.github.get_issue(issue.number)
        if not fresh.is_open:
            return "the issue closed while the run was in progress"
        if not fresh.has_label(policy.issueLabel):
            return f"the issue no longer carries {policy.issueLabel}"

        verdict = self.scheduler.evaluate([fresh])[0]
        if verdict.runnability not in (Runnability.RUNNABLE, Runnability.CLAIMED):
            return f"the issue is no longer eligible: {verdict.render()}"

        pull = self.github.get_pull(pull_number)
        if pull.state != "OPEN":
            return f"pull request #{pull_number} is {pull.state}"
        if pull.head_sha != head_sha:
            return (
                f"the pull request head is {pull.head_sha[:12]}, and the verified "
                f"commit is {head_sha[:12]}"
            )
        if pull.base_ref != policy.baseBranch:
            return f"the pull request targets {pull.base_ref}"
        if pull.mergeable == "CONFLICTING":
            return "the pull request has a merge conflict"
        if pull.mergeable == "UNKNOWN":
            return "GitHub has not decided whether the pull request merges cleanly"

        if agent_run is not None and agent_run.checks_passed is False:
            return "the deterministic checks did not pass"

        review = agent_run.review if agent_run else {"ran": False, "reason": "adopted"}
        if not review.get("ran"):
            if policy.reviewPolicy == "required":
                return "the policy requires an independent review, and none ran"
            if not policy.merge_is_permitted_without_review():
                return (
                    "no independent review ran, and mergeWithoutReview is off"
                )
        return ""

    def _after_merge(self, issue, branch, pull_number, result) -> None:
        policy = self.policy
        self.github.remove_label(issue.number, policy.inProgressLabel)
        for _ in range(6):
            fresh = self.github.get_issue(issue.number)
            if not fresh.is_open:
                break
            self.sleep(2)
        else:
            if policy.closeIssueIfPullRequestDidNot:
                self.github.close_issue(issue.number)
                result.detail += "; the issue was closed by the coordinator"
            else:
                result.detail += "; the issue did not close on its own"
        if policy.deleteRemoteBranchOnMerge:
            self.github.delete_branch(branch, policy.branchPrefix)
        if policy.deleteLocalBranchOnMerge:
            self.git.delete_local_branch(branch, policy.branchPrefix)
        self.git.fetch()

    def _after_failed_agent(self, issue, run_id, result, agent_run) -> IssueResult:
        result.outcome = agent_run.outcome
        result.detail = f"agentbox exited {agent_run.exit_code}"
        if agent_run.outcome is Outcome.FAILED_TRANSIENT:
            result.detail += " (transient)"
        return self._flag_failed(issue, run_id, result)

    def _flag_human(self, issue, run_id, result, pull=None) -> IssueResult:
        result.outcome = Outcome.NEEDS_HUMAN
        if not self.dry_run:
            self.github.add_label(issue.number, self.policy.humanLabel)
            self.github.create_comment(
                issue.number,
                prompts.needs_human_comment(run_id, "the queue cannot finish this issue",
                                            result.detail),
            )
        return result

    def _flag_failed(self, issue, run_id, result, pull=None) -> IssueResult:
        if not self.dry_run:
            self.github.add_label(issue.number, self.policy.failedLabel)
            self.github.create_comment(
                issue.number,
                prompts.needs_human_comment(run_id, "the implementation run failed",
                                            result.detail),
            )
        return result

    def _needs_human(self, issue, run_id, reason, detail) -> IssueResult:
        result = IssueResult(issue.number, Outcome.NEEDS_HUMAN, f"{reason}: {detail}")
        return self._flag_human(issue, run_id, result)
