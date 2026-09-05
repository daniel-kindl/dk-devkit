"""The value types the coordinator passes around, and the outcome taxonomy.

Nothing here performs input or output. Every function is total and
deterministic, so the scheduler and the classifier can be tested with no
GitHub, no git and no container.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from typing import Dict, List, Optional, Sequence


# --------------------------------------------------------------- outcomes --


class Outcome(enum.Enum):
    """What one issue did, and what the queue must do next.

    The distinction that matters is the last one. A product failure belongs to
    one issue, and the queue continues with another. A security or integrity
    failure belongs to the whole machine, and the queue stops at once.
    """

    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED_TRANSIENT = "FAILED_TRANSIENT"
    FAILED_FINAL = "FAILED_FINAL"
    SECURITY_OR_INTEGRITY_FAILURE = "SECURITY_OR_INTEGRITY_FAILURE"

    @property
    def stops_queue(self) -> bool:
        return self is Outcome.SECURITY_OR_INTEGRITY_FAILURE


class Runnability(enum.Enum):
    """Why the scheduler will or will not start an issue."""

    RUNNABLE = "RUNNABLE"
    BLOCKED = "BLOCKED"
    CLAIMED = "CLAIMED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    AMBIGUOUS = "AMBIGUOUS"
    CYCLE = "CYCLE"
    INELIGIBLE = "INELIGIBLE"


# ------------------------------------------------------------ GitHub state --


@dataclasses.dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str  # "open" or "closed"
    labels: tuple = ()
    url: str = ""

    @property
    def is_open(self) -> bool:
        return self.state.lower() == "open"

    def has_label(self, name: str) -> bool:
        return name in self.labels


@dataclasses.dataclass(frozen=True)
class Comment:
    id: int
    body: str
    author: str = ""
    created_at: str = ""


@dataclasses.dataclass(frozen=True)
class PullRequest:
    number: int
    state: str  # "OPEN", "CLOSED" or "MERGED"
    head_ref: str
    base_ref: str
    head_sha: str
    merged: bool = False
    mergeable: str = "UNKNOWN"  # MERGEABLE, CONFLICTING or UNKNOWN
    merge_state_status: str = "UNKNOWN"
    url: str = ""


@dataclasses.dataclass(frozen=True)
class CheckRun:
    name: str
    status: str  # queued, in_progress or completed
    conclusion: str = ""  # success, failure, neutral, skipped, ...

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def passed(self) -> bool:
        # A neutral or skipped check is not a failure. GitHub reports a job
        # that a condition turned off as "skipped", and blocking on that would
        # stop every conditional workflow.
        return self.completed and self.conclusion in ("success", "neutral", "skipped")


# --------------------------------------------------------------- decisions --


@dataclasses.dataclass(frozen=True)
class Verdict:
    """The scheduler's answer for one issue."""

    issue: int
    runnability: Runnability
    reason: str = ""
    blockers: tuple = ()

    def render(self) -> str:
        head = f"#{self.issue} {self.runnability.value}"
        if self.blockers:
            head += " by " + ", ".join(f"#{b}" for b in self.blockers)
        if self.reason:
            head += f" ({self.reason})"
        return head


@dataclasses.dataclass
class IssueResult:
    """What the coordinator did with one issue in one drain."""

    issue: int
    outcome: Outcome
    detail: str = ""
    branch: str = ""
    pull_request: Optional[int] = None
    agentbox_runs: int = 0
    ci_retries: int = 0
    merged: bool = False


# ---------------------------------------------------------- branch naming --

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def branch_slug(title: str, limit: int = 40) -> str:
    """A short, stable, lower-case slug for a branch name.

    The slug is derived from the issue title, so the same issue always names
    the same branch. A branch that already exists can therefore be recognised
    and adopted instead of being made a second time.
    """
    slug = _SLUG_STRIP.sub("-", title.lower()).strip("-")
    if len(slug) > limit:
        slug = slug[:limit].rstrip("-")
    return slug


def branch_for_issue(prefix: str, number: int, title: str) -> str:
    """``agent/issue-<n>-<slug>``, or ``agent/issue-<n>`` with no usable slug.

    The caller must still put the result through ``git check-ref-format``. A
    title can hold anything, and this function only removes what it knows
    about.
    """
    slug = branch_slug(title)
    stem = f"{prefix}issue-{number}"
    return f"{stem}-{slug}" if slug else stem


# ------------------------------------------------ agentbox result decoding --

# The refusals bin/agentbox prints at exit code 9. A refusal that names a
# product problem belongs to the issue. A refusal that names an integrity
# problem belongs to the machine, and it stops the queue.
#
# The list is deliberately a list of the SAFE refusals. Anything else at exit
# code 9 is treated as an integrity failure, because "the import could not be
# shown to be safe" and "the import was unsafe" call for the same answer.
_PRODUCT_REFUSALS = (
    "the agent produced no commit",
    "the result is identical to the base commit",
    "and the limit is",
    "merge commit(s)",
    "the result does not descend from the base commit",
)

_INTEGRITY_MARKERS = (
    "DISPOSABLE CLONE INTEGRITY FAILED",
    "DISPOSABLE CLONE INTEGRITY UNKNOWN",
    "an isolation probe failed",
    "the repository changed while the run was in progress",
    "the import changed more than the agent branch",
    "moved while the run was in progress",
    "the fetched commit is not the validated one",
    "configuration could not be restored",
    "still has hooks after sanitising",
    "still has an alternates file",
)


def classify_agentbox_exit(code: int, output: str) -> Outcome:
    """Map one agentbox run onto the outcome taxonomy.

    ``output`` is the combined agentbox log. It is searched for the markers
    that only an isolation or integrity failure produces, because those must
    stop the whole queue even when the exit code alone looks ordinary.
    """
    for marker in _INTEGRITY_MARKERS:
        if marker in output:
            return Outcome.SECURITY_OR_INTEGRITY_FAILURE

    if code == 0:
        return Outcome.SUCCESS
    if code == 11:
        return Outcome.BLOCKED  # another run holds the branch
    if code in (3, 4, 5, 6):
        return Outcome.NEEDS_HUMAN  # the machine is not ready
    if code == 7:
        return Outcome.FAILED_FINAL  # the branch name is unsafe
    if code in (8, 10):
        return Outcome.FAILED_TRANSIENT  # the agent failed, or ran out of time
    if code == 9:
        if any(marker in output for marker in _PRODUCT_REFUSALS):
            return Outcome.FAILED_FINAL
        return Outcome.SECURITY_OR_INTEGRITY_FAILURE
    return Outcome.FAILED_FINAL


AGENTBOX_SUMMARY_START = "===AGENTBOX_SUMMARY_JSON==="
AGENTBOX_SUMMARY_END = "===END==="


def extract_agentbox_summary(output: str) -> Optional[dict]:
    """Read the JSON summary block that the orchestrator prints.

    Returns ``None`` when the block is absent, which is what a run that died
    before the report looks like.
    """
    import json

    start = output.rfind(AGENTBOX_SUMMARY_START)
    if start < 0:
        return None
    start += len(AGENTBOX_SUMMARY_START)
    end = output.find(AGENTBOX_SUMMARY_END, start)
    if end < 0:
        return None
    try:
        return json.loads(output[start:end])
    except ValueError:
        return None


# ------------------------------------------------------------- check state --


def check_verdict(
    runs: Sequence[CheckRun],
    required: Sequence[str],
    require_any: bool,
) -> Dict[str, object]:
    """Decide whether the GitHub checks of one commit allow a merge.

    ``required`` names the checks that must be present and must pass. An empty
    ``required`` means "every check that reported". ``require_any`` refuses a
    commit that reported no check at all, which is the fail-closed answer when
    a workflow did not start.
    """
    by_name = {r.name: r for r in runs}
    missing: List[str] = [name for name in required if name not in by_name]
    watched = [by_name[n] for n in required if n in by_name] if required else list(runs)

    pending = [r.name for r in watched if not r.completed]
    failed = [r.name for r in watched if r.completed and not r.passed]

    if not runs and require_any:
        return {"state": "none", "pending": [], "failed": [], "missing": list(required)}
    if missing:
        return {"state": "missing", "pending": pending, "failed": failed, "missing": missing}
    if pending:
        return {"state": "pending", "pending": pending, "failed": failed, "missing": []}
    if failed:
        return {"state": "failed", "pending": [], "failed": failed, "missing": []}
    return {"state": "passed", "pending": [], "failed": [], "missing": []}
