"""In-memory doubles for the agentqueue tests.

Each double carries the same method surface as the real class, and records
every change. The tests can then assert two different things:

    what the coordinator decided
    what it changed, and that a dry run changed nothing

Nothing here reaches GitHub, git or Podman.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if os.path.join(_ROOT, "lib") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "lib"))

from agentqueue.ghapi import DryRunViolation  # noqa: E402
from agentqueue.model import (  # noqa: E402
    CheckRun,
    Comment,
    Issue,
    Outcome,
    PullRequest,
)
from agentqueue.runner import AgentRun  # noqa: E402

REPO_ROOT = _ROOT
AGENT_IDENTITY = "Agent <agent@local>"


class FakeGitHub:
    def __init__(self, owner="acme", name="widget", dry_run=False):
        self.owner = owner
        self.name = name
        self.dry_run = dry_run
        self.mutations: List[str] = []
        self.issues: Dict[int, Issue] = {}
        self.comments: Dict[int, List[Comment]] = {}
        self.dependencies: Dict[int, Optional[List[int]]] = {}
        self.native_dependencies = True
        self.pulls: Dict[int, PullRequest] = {}
        self.checks: Dict[str, List[CheckRun]] = {}
        self.logs: Dict[str, str] = {}
        self._next_comment = 1000
        self._next_pull = 500
        self.merge_calls: List[tuple] = []
        self.merge_should_conflict = False
        # maxParallel above 1 drives this double from several threads. The
        # counters below hand out identities, and two issues that were given
        # the same pull request number would be a defect of the double, not of
        # the coordinator.
        self._counters = threading.Lock()

    # ------------------------------------------------------------ helpers --

    def add_issue(self, number, title="T", body="", state="open", labels=()):
        self.issues[number] = Issue(number, title, body, state, tuple(labels),
                                    f"https://example.invalid/{number}")
        self.comments.setdefault(number, [])
        return self.issues[number]

    def _mutate(self, description):
        if self.dry_run:
            raise DryRunViolation(f"a dry run tried to: {description}")
        self.mutations.append(description)

    # --------------------------------------------------------------- read --

    def list_issues(self, label):
        return [
            i for i in sorted(self.issues.values(), key=lambda x: x.number)
            if i.is_open and label in i.labels
        ]

    def get_issue(self, number):
        if number not in self.issues:
            raise KeyError(f"no issue #{number}")
        return self.issues[number]

    def list_comments(self, number):
        return list(self.comments.get(number, []))

    def blocked_by(self, number):
        if not self.native_dependencies:
            return None
        return list(self.dependencies.get(number, []) or [])

    def find_pull_for_branch(self, branch):
        found = [p for p in self.pulls.values() if p.head_ref == branch]
        if not found:
            return None
        found.sort(key=lambda p: p.number)
        for pull in reversed(found):
            if pull.state == "OPEN":
                return pull
        return found[-1]

    def get_pull(self, number):
        # GitHub moves the head of an open pull request when the branch is
        # pushed. A double that did not would make every repair look like a
        # head that somebody else moved.
        pull = self.pulls[number]
        if pull.state == "OPEN":
            current = self.head_sha_for(pull.head_ref)
            if current != pull.head_sha:
                pull = PullRequest(
                    pull.number, pull.state, pull.head_ref, pull.base_ref,
                    current, pull.merged, pull.mergeable,
                    pull.merge_state_status, pull.url,
                )
                self.pulls[number] = pull
        return pull

    def check_runs(self, sha):
        return list(self.checks.get(sha, []))

    def failing_run_log(self, sha, max_bytes=12000):
        return self.logs.get(sha, "")

    # -------------------------------------------------------------- write --

    def add_label(self, number, label):
        self._mutate(f"add label {label} to #{number}")
        issue = self.issues[number]
        if label not in issue.labels:
            self.issues[number] = Issue(
                issue.number, issue.title, issue.body, issue.state,
                issue.labels + (label,), issue.url,
            )

    def remove_label(self, number, label):
        self._mutate(f"remove label {label} from #{number}")
        issue = self.issues[number]
        self.issues[number] = Issue(
            issue.number, issue.title, issue.body, issue.state,
            tuple(l for l in issue.labels if l != label), issue.url,
        )

    def create_comment(self, number, body):
        self._mutate(f"comment on #{number}")
        with self._counters:
            self._next_comment += 1
            identity = self._next_comment
        self.comments.setdefault(number, []).append(
            Comment(identity, body, "agentqueue", "")
        )
        return identity

    def delete_comment(self, comment_id):
        self._mutate(f"delete comment {comment_id}")
        for number, items in self.comments.items():
            self.comments[number] = [c for c in items if c.id != comment_id]

    def close_issue(self, number):
        self._mutate(f"close #{number}")
        issue = self.issues[number]
        self.issues[number] = Issue(
            issue.number, issue.title, issue.body, "closed", issue.labels, issue.url,
        )

    def create_pull(self, title, body, head, base):
        self._mutate(f"open a pull request for {head}")
        with self._counters:
            self._next_pull += 1
            number = self._next_pull
        pull = PullRequest(
            number, "OPEN", head, base,
            self.head_sha_for(head), False, "MERGEABLE", "CLEAN",
            f"https://example.invalid/pull/{number}",
        )
        self.pulls[pull.number] = pull
        return pull

    def update_pull_body(self, number, body):
        self._mutate(f"update the body of #{number}")

    def merge_pull(self, number, method, expected_sha):
        self._mutate(f"merge #{number}")
        self.merge_calls.append((number, method, expected_sha))
        pull = self.pulls[number]
        if pull.head_sha != expected_sha:
            raise RuntimeError("the head moved")
        if self.merge_should_conflict:
            raise RuntimeError("merge conflict")
        self.pulls[number] = PullRequest(
            pull.number, "MERGED", pull.head_ref, pull.base_ref, pull.head_sha,
            True, pull.mergeable, pull.merge_state_status, pull.url,
        )
        issue = self._issue_of_pull(pull)
        if issue is not None:
            self.issues[issue] = Issue(
                self.issues[issue].number, self.issues[issue].title,
                self.issues[issue].body, "closed", self.issues[issue].labels,
                self.issues[issue].url,
            )
        return {"merged": True}

    def _issue_of_pull(self, pull):
        for number in self.issues:
            if f"issue-{number}" in pull.head_ref:
                return number
        return None

    def delete_branch(self, branch, prefix="agent/"):
        if not branch.startswith(prefix):
            raise RuntimeError(f"refusing to delete {branch}")
        self._mutate(f"delete the remote branch {branch}")

    # -------------------------------------------------------------- glue --

    head_sha_source = None

    def head_sha_for(self, branch):
        if self.head_sha_source is not None:
            return self.head_sha_source(branch)
        return "sha-" + branch


class FakeGit:
    def __init__(self, root="/fake/repo", base="basesha0000000000000000000000000000000"):
        self.root = root
        self.dry_run = False
        self.mutations: List[str] = []
        self.refs: Dict[str, str] = {"refs/remotes/origin/main": base}
        self.pushed: List[str] = []
        self.audits: Dict[str, object] = {}
        self.busy = ""
        self.checked_out = "main"
        self.diffs: Dict[str, str] = {}

    def _mutate(self, description):
        if self.dry_run:
            raise RuntimeError(f"a dry run tried to: {description}")
        self.mutations.append(description)

    def is_repository(self):
        return True

    def remote_slug(self, remote="origin"):
        return ("acme", "widget")

    def rev_parse(self, ref):
        return self.refs.get(ref) or self.refs.get(f"refs/heads/{ref}")

    def ref_exists(self, ref):
        return self.rev_parse(ref) is not None

    def current_branch(self):
        return self.checked_out

    def operation_in_progress(self):
        return self.busy

    def check_ref_format(self, branch):
        return " " not in branch and ".." not in branch and not branch.endswith("/")

    def branches_with_prefix(self, prefix):
        return [
            r[len("refs/heads/"):]
            for r in self.refs
            if r.startswith(f"refs/heads/{prefix}")
        ]

    def branches_for_issue(self, prefix, number):
        stem = f"{prefix}issue-{number}"
        return [b for b in self.branches_with_prefix(prefix)
                if b == stem or b.startswith(stem + "-")]

    def audit_branch(self, branch, base_ref, max_commits, allow_merges,
                     identities, require_agent_authored):
        return self.audits[branch]

    def diff_text(self, base, tip, max_bytes=4_000_000):
        return self.diffs.get(tip, "diff --git a/x b/x\n+ordinary change\n")

    def push_branch(self, branch, prefix="agent/", remote="origin"):
        if not branch.startswith(prefix):
            raise RuntimeError(f"refusing to push {branch}")
        self._mutate(f"push {branch}")
        self.pushed.append(branch)

    def delete_local_branch(self, branch, prefix):
        self._mutate(f"delete {branch}")

    def fetch(self, remote="origin"):
        self._mutate("fetch")


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class FakeRunner:
    """A scripted agentbox.

    ``script`` holds one entry per call. Each entry may set the exit code, the
    summary, the branch tip the run leaves behind, the structured progress
    events the run publishes, and the raw lines it prints. The last two make
    the presentation layer testable without a model, a container or a clock:
    a fake event stream proves the display exactly as a real one would.
    """

    def __init__(self, git: FakeGit, script=None):
        self.git = git
        self.script = list(script or [])
        self.calls: List[dict] = []
        self.dry_run = False
        self.agent_output = "progress"

    def run(self, repo, branch, prompt_file, base_ref, continuation=False,
            log_name="agentbox", log_dir="", on_event=None, on_raw=None,
            effort=None):
        step = self.script.pop(0) if self.script else {}
        self.calls.append(
            {"branch": branch, "continuation": continuation,
             "prompt": _read(prompt_file),
             "log_name": log_name, "log_dir": log_dir,
             "effort": effort}
        )
        for item in step.get("events", []):
            if on_event is not None:
                on_event(item)
        for line in step.get("raw", []):
            if on_raw is not None:
                on_raw(line)
        code = step.get("exit", 0)
        output = step.get("output", "")
        summary = step.get("summary")
        if summary is None and code == 0:
            summary = {
                "checksPassed": step.get("checks_passed", True),
                "failedChecks": step.get("failed_checks", []),
                "fixRounds": step.get("fix_rounds", 0),
                "review": step.get("review", {"skipped": True, "reason": "no credential"}),
                "resultCommit": step.get("sha", f"sha-{branch}-{len(self.calls)}"),
            }
        if code == 0:
            self.git.refs[f"refs/heads/{branch}"] = (
                summary or {}
            ).get("resultCommit", f"sha-{branch}-{len(self.calls)}")
        from agentqueue.model import classify_agentbox_exit

        return AgentRun(
            exit_code=code,
            outcome=classify_agentbox_exit(code, output),
            output=output,
            summary=summary,
            duration_seconds=1,
            command=["agentbox"],
            log_path=os.path.join(log_dir or "/fake/logs", f"{log_name}.log"),
        )


def make_catalog(path=None):
    """The repository's own model tier catalog, as the tests read it."""
    from agentqueue import effort as effort_mod

    return effort_mod.load(path or effort_mod.manifest_path(REPO_ROOT))


def make_policy(**overrides):
    from agentqueue import policy as policy_mod

    pol = policy_mod.load(
        "/nonexistent",
        os.path.join(REPO_ROOT, "config", "agentqueue", "policy.default.json"),
    )
    for key, value in overrides.items():
        setattr(pol, key, value)
    pol.validate()
    return pol
