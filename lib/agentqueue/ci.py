"""Wait for the GitHub checks of one commit, and decide what they mean.

Three answers matter, and each has one safe response.

    passed    continue to the merge gates
    failed    collect the evidence and try a bounded repair
    anything  do not merge

"Anything else" covers a timeout, a missing required check, and a commit that
reported no check at all. Each one leaves the merge undecided, and an
undecided merge is a refusal. The queue never merges on uncertainty.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Callable, List, Optional, Sequence

from .model import CheckRun, check_verdict


@dataclasses.dataclass
class CiResult:
    state: str  # passed, failed, pending, missing, none or timeout
    failed: tuple = ()
    pending: tuple = ()
    missing: tuple = ()
    waited_seconds: int = 0
    runs: tuple = ()

    @property
    def passed(self) -> bool:
        return self.state == "passed"

    def render(self) -> str:
        if self.state == "passed":
            return f"all checks passed after {self.waited_seconds}s"
        if self.state == "failed":
            return "failed checks: " + ", ".join(self.failed)
        if self.state == "missing":
            return "required checks never reported: " + ", ".join(self.missing)
        if self.state == "none":
            return f"no check reported within {self.waited_seconds}s"
        if self.state == "timeout":
            return (
                f"still running after {self.waited_seconds}s: "
                + ", ".join(self.pending)
            )
        return self.state


def check_progress(state: str, verdict) -> str:
    """One short, factual line about the checks of one commit.

    It names the state and, at most, the first three checks the state is about.
    It never estimates how much longer they will take, because nothing here
    knows that.
    """
    names = list(verdict.get("pending") or []) or list(verdict.get("failed") or [])
    if not names:
        names = list(verdict.get("missing") or [])
    if not names:
        return state
    shown = ", ".join(names[:3])
    if len(names) > 3:
        shown += f" +{len(names) - 3}"
    return f"{state}: {shown}"


def wait_for_checks(
    github,
    sha: str,
    policy,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    emit: Optional[Callable[[str], None]] = None,
    ui=None,
) -> CiResult:
    """Poll the checks of ``sha`` until they settle, or until the limit.

    ``ui`` receives the state of the checks as deterministic progress: the
    state name and the checks that are still running. It is display only, and
    it changes no decision below.
    """
    say = emit or (lambda line: None)
    started = clock()
    last_state = ""

    while True:
        waited = int(clock() - started)
        runs: List[CheckRun] = github.check_runs(sha)
        verdict = check_verdict(
            runs, policy.requiredChecks, policy.requireCiChecks
        )
        state = str(verdict["state"])

        if state != last_state:
            say(f"checks for {sha[:12]}: {state}")
            last_state = state
        if ui is not None:
            ui.stage_detail(check_progress(state, verdict), key=state)

        if state in ("passed", "failed"):
            return CiResult(
                state=state,
                failed=tuple(verdict["failed"]),
                pending=tuple(verdict["pending"]),
                missing=tuple(verdict["missing"]),
                waited_seconds=waited,
                runs=tuple(runs),
            )

        # A workflow needs a moment to appear. "No check yet" is only an
        # answer after the grace window, and then it is a refusal.
        if state == "none" and waited >= policy.ciGraceSeconds:
            return CiResult(state="none", waited_seconds=waited, runs=tuple(runs))
        if state == "missing" and waited >= policy.ciGraceSeconds:
            return CiResult(
                state="missing",
                missing=tuple(verdict["missing"]),
                waited_seconds=waited,
                runs=tuple(runs),
            )

        if waited >= policy.ciTimeoutSeconds:
            return CiResult(
                state="timeout",
                pending=tuple(verdict["pending"]),
                missing=tuple(verdict["missing"]),
                waited_seconds=waited,
                runs=tuple(runs),
            )
        sleep(policy.ciPollSeconds)
