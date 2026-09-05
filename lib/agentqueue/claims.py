"""Claiming an issue, so that two coordinators do not implement it twice.

The claim is durable GitHub state, because a coordinator can be killed and a
second one can start on another machine. Two parts carry it:

    a label      agent-in-progress, which a human also sees in the issue list
    a comment    a machine-readable record of the run that holds the claim

The comment is the authority, because a label carries no run id, no branch and
no start time. The label is the human-visible half of the same fact.

GitHub offers no compare-and-swap on a label, so the claim is best effort and
it says so. The race is narrowed like this:

    1. add the label
    2. post the claim comment
    3. read every comment back
    4. the OLDEST live claim wins

A coordinator that finds an older live claim deletes its own comment and
leaves the issue alone. Two coordinators that start within the same second
therefore agree on one winner, because they agree on the comment order.

A local lock directory holds the same claim on this machine, so two runs
started from one terminal stop immediately, with no GitHub call at all.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import socket
import time
from typing import List, Optional, Sequence

from .model import Comment, Issue

# These markers are a durable wire-format identifier. Keep them stable so
# claims written by agentqueue remain readable after the CLI became agentq.
CLAIM_MARKER = "<!-- agentqueue:claim v1 -->"
RELEASE_MARKER = "<!-- agentqueue:release v1 -->"

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@dataclasses.dataclass(frozen=True)
class Claim:
    run_id: str
    issue: int
    branch: str
    base_commit: str
    started_at: str
    started_epoch: int
    host: str
    coordinator: str
    timeout_seconds: int
    comment_id: int = 0

    def age_seconds(self, now: Optional[int] = None) -> int:
        return int(now if now is not None else time.time()) - self.started_epoch


def _payload_of(comment: Comment) -> Optional[dict]:
    match = _JSON_BLOCK.search(comment.body)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def parse_claim(comment: Comment) -> Optional[Claim]:
    if CLAIM_MARKER not in comment.body:
        return None
    payload = _payload_of(comment)
    if not payload or payload.get("kind") != "claim":
        return None
    try:
        return Claim(
            run_id=str(payload["runId"]),
            issue=int(payload["issue"]),
            branch=str(payload.get("branch", "")),
            base_commit=str(payload.get("baseCommit", "")),
            started_at=str(payload.get("startedAt", "")),
            started_epoch=int(payload.get("startedEpoch", 0)),
            host=str(payload.get("host", "")),
            coordinator=str(payload.get("coordinator", "")),
            timeout_seconds=int(payload.get("timeoutSeconds", 0)),
            comment_id=comment.id,
        )
    except (KeyError, TypeError, ValueError):
        return None


def released_run_ids(comments: Sequence[Comment]) -> List[str]:
    out: List[str] = []
    for comment in comments:
        if RELEASE_MARKER not in comment.body:
            continue
        payload = _payload_of(comment)
        if payload and payload.get("kind") == "release" and payload.get("runId"):
            out.append(str(payload["runId"]))
    return out


def live_claims(
    comments: Sequence[Comment],
    stale_after_seconds: int,
    now: Optional[int] = None,
) -> List[Claim]:
    """Every claim that is neither released nor stale, oldest first.

    A claim whose run recorded its own limit is judged against that limit plus
    a margin, so a short run does not hold an issue for the manifest maximum.
    """
    released = set(released_run_ids(comments))
    out: List[Claim] = []
    for comment in comments:
        claim = parse_claim(comment)
        if claim is None or claim.run_id in released:
            continue
        limit = stale_after_seconds
        if claim.timeout_seconds > 0:
            limit = min(limit, claim.timeout_seconds * 2 + 900)
        if claim.started_epoch and claim.age_seconds(now) > limit:
            continue
        out.append(claim)
    out.sort(key=lambda c: (c.comment_id, c.run_id))
    return out


def stale_claims(
    comments: Sequence[Comment],
    stale_after_seconds: int,
    now: Optional[int] = None,
) -> List[Claim]:
    """Claims that are neither released nor live. They are reported, not hidden."""
    released = set(released_run_ids(comments))
    live_ids = {c.run_id for c in live_claims(comments, stale_after_seconds, now)}
    out: List[Claim] = []
    for comment in comments:
        claim = parse_claim(comment)
        if claim is None:
            continue
        if claim.run_id in released or claim.run_id in live_ids:
            continue
        out.append(claim)
    return out


def claim_body(claim: Claim) -> str:
    payload = {
        "kind": "claim",
        "version": 1,
        "runId": claim.run_id,
        "issue": claim.issue,
        "branch": claim.branch,
        "baseCommit": claim.base_commit,
        "startedAt": claim.started_at,
        "startedEpoch": claim.started_epoch,
        "host": claim.host,
        "coordinator": claim.coordinator,
        "timeoutSeconds": claim.timeout_seconds,
    }
    return (
        f"{CLAIM_MARKER}\n"
        "**agentq** claimed this issue for an unattended implementation run.\n\n"
        f"- run `{claim.run_id}`\n"
        f"- branch `{claim.branch}`\n"
        f"- base commit `{claim.base_commit[:12]}`\n"
        f"- started `{claim.started_at}`\n\n"
        "The agent works in a disposable clone inside a sandbox. It holds no "
        "GitHub credential. Only the coordinator pushes, opens a pull request "
        "or merges.\n\n"
        "```json\n" + json.dumps(payload, sort_keys=True) + "\n```\n"
    )


def release_body(run_id: str, issue: int, outcome: str, detail: str) -> str:
    payload = {
        "kind": "release",
        "version": 1,
        "runId": run_id,
        "issue": issue,
        "outcome": outcome,
    }
    return (
        f"{RELEASE_MARKER}\n"
        f"**agentq** released this issue. Outcome: **{outcome}**.\n\n"
        f"{detail}\n\n"
        "```json\n" + json.dumps(payload, sort_keys=True) + "\n```\n"
    )


class ClaimStore:
    """Read and write claims for one repository."""

    def __init__(self, github, policy, coordinator: str, dry_run: bool = False):
        self.github = github
        self.policy = policy
        self.coordinator = coordinator
        self.dry_run = dry_run
        self.reclaimed: List[Claim] = []

    def live_claim(self, issue: Issue) -> Optional[Claim]:
        comments = self.github.list_comments(issue.number)
        claims = live_claims(comments, self.policy.staleClaimSeconds)
        return claims[0] if claims else None

    def stale_for(self, issue: Issue) -> List[Claim]:
        comments = self.github.list_comments(issue.number)
        return stale_claims(comments, self.policy.staleClaimSeconds)

    def acquire(self, issue: Issue, claim: Claim) -> Optional[Claim]:
        """Take the claim, or return the claim that already holds the issue.

        Returns ``None`` when this coordinator won. Returns the winning claim
        when it did not, and removes its own comment in that case.
        """
        stale = self.stale_for(issue)
        if stale:
            self.reclaimed.extend(stale)

        self.github.add_label(issue.number, self.policy.inProgressLabel)
        comment_id = self.github.create_comment(issue.number, claim_body(claim))
        mine = dataclasses.replace(claim, comment_id=comment_id)

        winners = live_claims(
            self.github.list_comments(issue.number), self.policy.staleClaimSeconds
        )
        if winners and winners[0].run_id != mine.run_id:
            self.github.delete_comment(comment_id)
            return winners[0]
        return None

    def release(self, issue_number: int, run_id: str, outcome: str, detail: str) -> None:
        self.github.create_comment(
            issue_number, release_body(run_id, issue_number, outcome, detail)
        )
        self.github.remove_label(issue_number, self.policy.inProgressLabel)


class LocalLockError(Exception):
    pass


class LocalLock:
    """One issue of one repository, held by one process on this machine.

    ``mkdir`` is the atomic primitive, exactly as in bin/agentbox. The lock is
    the cheap first gate; the GitHub claim is the durable one.
    """

    def __init__(self, root: str, key: str, timeout_seconds: int):
        self.dir = os.path.join(root, f"{key}.lock")
        self.timeout_seconds = timeout_seconds
        self.held = False

    def _owner(self) -> dict:
        try:
            with open(os.path.join(self.dir, "owner"), "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def is_stale(self) -> bool:
        owner = self._owner()
        if not owner:
            return True
        started = int(owner.get("started", 0))
        limit = int(owner.get("timeout", self.timeout_seconds)) + 900
        if started and time.time() - started > limit:
            return True
        pid = int(owner.get("pid", 0))
        if owner.get("host") == socket.gethostname() and pid:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        return False

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.dir), exist_ok=True)
        try:
            os.mkdir(self.dir)
        except FileExistsError:
            if not self.is_stale():
                raise LocalLockError(f"another agentq run holds {self.dir}")
            import shutil

            shutil.rmtree(self.dir, ignore_errors=True)
            os.mkdir(self.dir)
        with open(os.path.join(self.dir, "owner"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "started": int(time.time()),
                    "timeout": self.timeout_seconds,
                },
                handle,
            )
        self.held = True

    def release(self) -> None:
        if not self.held:
            return
        import shutil

        shutil.rmtree(self.dir, ignore_errors=True)
        self.held = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()
        return False
