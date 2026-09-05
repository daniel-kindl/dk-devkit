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
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import time
from typing import Callable, List, Optional, Sequence

from .model import Outcome, classify_agentbox_exit, extract_agentbox_summary


@dataclasses.dataclass
class AgentRun:
    exit_code: int
    outcome: Outcome
    output: str
    summary: Optional[dict]
    duration_seconds: int
    command: List[str]

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
    ):
        self.agentbox = agentbox
        self.policy = policy
        self.log_dir = log_dir
        self.dry_run = dry_run
        self.emit = emit or (lambda line: None)

    def command(
        self,
        repo: str,
        branch: str,
        prompt_file: str,
        base_ref: str,
        continuation: bool = False,
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
    ) -> AgentRun:
        cmd = self.command(repo, branch, prompt_file, base_ref, continuation)
        if self.dry_run:
            raise RuntimeError("a dry run tried to start agentbox")

        started = time.time()
        self.emit(f"    agentbox: {' '.join(cmd[1:6])} ...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        chunks: List[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            self.emit("      " + line.rstrip())
        proc.wait()
        output = "".join(chunks)

        os.makedirs(self.log_dir, exist_ok=True)
        log_path = os.path.join(self.log_dir, f"{log_name}.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(output)

        return AgentRun(
            exit_code=proc.returncode,
            outcome=classify_agentbox_exit(proc.returncode, output),
            output=output,
            summary=extract_agentbox_summary(output),
            duration_seconds=int(time.time() - started),
            command=cmd,
        )
