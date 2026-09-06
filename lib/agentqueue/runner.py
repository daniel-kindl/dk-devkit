"""Drive bin/agentbox, and read what it produced.

agentqueue never runs an agent itself. It writes a prompt file, calls
agentbox, and waits. agentbox owns every isolation invariant, and this module
adds none and removes none.

Two run shapes:

    fresh        --base <remote base>, a new agent/* branch
    continuation --continue, the same branch, based on its own tip

A continuation is how a repair reaches an existing branch. The alternative,
editing an imported branch on the host with an untrusted agent, would put
model output outside the sandbox, so it is not available here.

Two streams come back from the child, on the same pipe:

    ===AGENTBOX_EVENT=== {...}   one structured lifecycle transition
    anything else                ordinary output, and model output

The first drives the stage display. The second is evidence: every line is
written to the run log as it arrives, and only ``--debug`` puts it on the
terminal. The classification is an exact prefix match, never a pattern against
prose, so the display cannot be steered by what a model chooses to print.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import time
from typing import Callable, List, Optional, Sequence

from .model import (
    Outcome,
    classify_agentbox_exit,
    extract_agentbox_summary,
    parse_agentbox_event,
)


@dataclasses.dataclass
class AgentRun:
    exit_code: int
    outcome: Outcome
    output: str
    summary: Optional[dict]
    duration_seconds: int
    command: List[str]
    log_path: str = ""

    @property
    def checks_passed(self) -> Optional[bool]:
        if not self.summary:
            return None
        return self.summary.get("checksPassed")

    @property
    def failed_checks(self) -> List[str]:
        """The checks that fail NOW, not the ones that failed at some point.

        The orchestrator repairs itself inside the sandbox, so an early
        failure is often already fixed. It publishes the final state under
        ``failedChecks`` for exactly this reason.
        """
        if not self.summary:
            return []
        entries = self.summary.get("failedChecks")
        if entries is None:
            entries = [
                e
                for e in self.summary.get("finalChecks", []) or []
                if e.get("exitCode") not in (0, None)
            ]
        return [e.get("command", "") for e in entries if e.get("command")]

    @property
    def failure_evidence(self) -> str:
        """What a repair prompt needs: the failing command and its output."""
        entries = (self.summary or {}).get("failedChecks") or []
        if not entries:
            return self.output[-6000:]
        return "\n\n".join(
            f"$ {e.get('command', '')}   (exit {e.get('exitCode')})\n"
            f"{e.get('tail', '')}"
            for e in entries
        )

    @property
    def fix_rounds(self) -> int:
        return int((self.summary or {}).get("fixRounds", 0) or 0)

    @property
    def review(self) -> dict:
        review = (self.summary or {}).get("review")
        if not review:
            return {"ran": False, "reason": "the review step did not run"}
        if review.get("skipped"):
            return {"ran": False, "reason": review.get("reason", "skipped")}
        return {"ran": True, "agent": "codex"}

    @property
    def result_commit(self) -> str:
        return (self.summary or {}).get("resultCommit") or ""


class AgentboxRunner:
    """Build and run one agentbox command."""

    def __init__(
        self,
        agentbox: str,
        policy,
        log_dir: str,
        dry_run: bool = False,
        emit: Optional[Callable[[str], None]] = None,
        agent_output: str = "progress",
    ):
        self.agentbox = agentbox
        self.policy = policy
        self.log_dir = log_dir
        self.dry_run = dry_run
        self.emit = emit or (lambda line: None)
        # "progress" asks the orchestrator for structured lifecycle events and
        # a line-oriented agent stream. "terminal" leaves agentbox in its own
        # default, which renders Sandcastle's interactive terminal UI. The
        # second is what --debug asks for, and it is the reason the first
        # exists: an interactive UI in a captured pipe is unreadable evidence.
        self.agent_output = agent_output

    def command(
        self,
        repo: str,
        branch: str,
        prompt_file: str,
        base_ref: str,
        continuation: bool = False,
        effort=None,
    ) -> List[str]:
        args = [
            self.agentbox,
            "pipeline",
            "--repo", repo,
            "--branch", branch,
            "--prompt-file", prompt_file,
            "--timeout", str(self.policy.agentTimeoutSeconds),
            "--max-commits", str(self.policy.maxCommits),
            "--max-iterations", str(self.policy.maxIterations),
            "--max-fix-rounds", str(self.policy.maxFixRounds),
            "--agent-output", self.agent_output,
        ]
        # The resolved tier reaches agentbox as pinned model IDs, never as a
        # tier name. agentbox runs what it is told to run, and the choice
        # stays in the trusted layer that can explain it.
        if effort is not None:
            args += [
                "--agent", effort.implementer.agent,
                "--model", effort.implementer.model,
            ]
            if self.policy.reviewPolicy != "none":
                args += [
                    "--review-agent", effort.reviewer.agent,
                    "--review-model", effort.reviewer.model,
                ]
        if continuation:
            # The branch is its own base. agentbox validates the descent and
            # updates the ref with a compare and swap, exactly as it does for
            # a fresh run.
            args += ["--continue"]
        else:
            args += ["--base", base_ref]
        if self.policy.reviewPolicy == "none":
            args += ["--review-agent", "none"]
        for check in self.policy.checks:
            args += ["--check", check]
        return args

    def run(
        self,
        repo: str,
        branch: str,
        prompt_file: str,
        base_ref: str,
        continuation: bool = False,
        log_name: str = "agentbox",
        log_dir: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
        on_raw: Optional[Callable[[str], None]] = None,
        effort=None,
    ) -> AgentRun:
        """Start agentbox, stream what it writes, and classify the result.

        The child's exit code, its summary block and its integrity markers are
        read exactly as before. What changed is where the lines GO: each one
        reaches the run log as it arrives, so an interrupted run still leaves
        its evidence behind, and the caller decides what a human sees.
        """
        cmd = self.command(repo, branch, prompt_file, base_ref, continuation, effort)
        if self.dry_run:
            raise RuntimeError("a dry run tried to start agentbox")

        started = time.time()
        self.emit(f"agentbox: {' '.join(cmd[1:6])} ...")

        directory = log_dir or self.log_dir
        os.makedirs(directory, exist_ok=True)
        log_path = os.path.join(directory, f"{log_name}.log")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        chunks: List[str] = []
        assert proc.stdout is not None
        # The log is the record of the run. It is opened before the first line
        # arrives and written line by line, and it is readable by its owner
        # only, because it holds whatever the child printed.
        handle = _open_private(log_path)
        try:
            for line in proc.stdout:
                chunks.append(line)
                handle.write(line)
                handle.flush()
                text = line.rstrip("\n")
                event = parse_agentbox_event(text)
                if event is not None:
                    if on_event is not None:
                        on_event(event)
                    continue
                if on_raw is not None:
                    on_raw(text)
                else:
                    self.emit(text)
            proc.wait()
        finally:
            # An interrupt must reach the caller, and the evidence must
            # survive it. Nothing here swallows the exception.
            handle.close()
            try:
                proc.stdout.close()
            except Exception:
                pass
        output = "".join(chunks)

        return AgentRun(
            exit_code=proc.returncode,
            outcome=classify_agentbox_exit(proc.returncode, output),
            output=output,
            summary=extract_agentbox_summary(output),
            duration_seconds=int(time.time() - started),
            command=cmd,
            log_path=log_path,
        )


def _open_private(path: str):
    """Open a log file that only its owner can read.

    agentbox redacts its own output before it prints it, and this file is a
    copy of what already reached the terminal. The mode is still 0600: a run
    log names branches, commands and check output, and none of that belongs to
    every account on the machine.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")
