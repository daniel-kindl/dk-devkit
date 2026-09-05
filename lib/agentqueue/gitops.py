"""Git against the REAL repository.

This is the trusted side. The repository belongs to the user, its hooks are
the user's own, and its configuration is honoured. That is the opposite of the
rule bin/agentbox applies to a disposable clone, and the difference is
deliberate: agentbox reads a git directory that model output could write, and
agentqueue reads one that only the user and agentbox itself have written.

What this module does NOT do:

    it never force-pushes
    it never moves the base branch
    it never commits, amends or rebases
    it never deletes a branch outside the agent namespace

The base commit for new work is always the remote-tracking ref, for example
``refs/remotes/origin/main``. The local base branch is left exactly as the
user left it, checked out or not.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
from typing import List, Optional, Sequence, Tuple


class GitError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class BranchAudit:
    """The result of judging one existing ``agent/*`` branch."""

    branch: str
    sha: str = ""
    commits: int = 0
    ok: bool = False
    reasons: Tuple[str, ...] = ()

    def render(self) -> str:
        if self.ok:
            return f"{self.branch} at {self.sha[:12]} ({self.commits} commit(s))"
        return f"{self.branch}: " + "; ".join(self.reasons)


class Git:
    def __init__(self, root: str, dry_run: bool = False):
        self.root = root
        self.dry_run = dry_run
        self.mutations: List[str] = []

    # ---------------------------------------------------------- plumbing --

    def run(self, args: Sequence[str], check: bool = True, timeout: int = 300):
        proc = subprocess.run(
            ["git", "-C", self.root, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def _mutate(self, description: str) -> None:
        if self.dry_run:
            raise RuntimeError(f"a dry run tried to: {description}")
        self.mutations.append(description)

    # -------------------------------------------------------------- facts --

    def is_repository(self) -> bool:
        code, out, _ = self.run(["rev-parse", "--is-inside-work-tree"], check=False)
        return code == 0 and out == "true"

    def remote_slug(self, remote: str = "origin") -> Tuple[str, str]:
        _, url, _ = self.run(["remote", "get-url", remote])
        match = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
        if not match:
            raise GitError(f"cannot read an owner and a name out of {url}")
        return match.group(1), match.group(2)

    def rev_parse(self, ref: str) -> Optional[str]:
        code, out, _ = self.run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                                check=False)
        return out or None if code == 0 else None

    def ref_exists(self, ref: str) -> bool:
        return self.rev_parse(ref) is not None

    def current_branch(self) -> str:
        code, out, _ = self.run(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
        return out if code == 0 else ""

    def is_clean(self) -> bool:
        _, out, _ = self.run(["status", "--porcelain"])
        return out == ""

    def operation_in_progress(self) -> str:
        """The name of an unfinished git operation, or an empty string.

        A repository in the middle of a merge, a rebase or a bisect is not a
        repository a coordinator should push out of.
        """
        _, gitdir, _ = self.run(["rev-parse", "--path-format=absolute", "--git-dir"])
        markers = {
            "MERGE_HEAD": "a merge",
            "CHERRY_PICK_HEAD": "a cherry-pick",
            "REVERT_HEAD": "a revert",
            "BISECT_LOG": "a bisect",
            "rebase-merge": "a rebase",
            "rebase-apply": "a rebase",
        }
        for name, label in markers.items():
            if os.path.exists(os.path.join(gitdir, name)):
                return label
        return ""

    def check_ref_format(self, branch: str) -> bool:
        code, _, _ = self.run(["check-ref-format", f"refs/heads/{branch}"], check=False)
        return code == 0

    def branches_with_prefix(self, prefix: str) -> List[str]:
        _, out, _ = self.run(
            ["for-each-ref", "--format=%(refname:short)", f"refs/heads/{prefix}*"]
        )
        return [line for line in out.splitlines() if line]

    def branches_for_issue(self, prefix: str, number: int) -> List[str]:
        """Every local branch that could hold the work for one issue.

        The generated name is deterministic, but an earlier run, or a human,
        may have used a different slug. Matching on ``<prefix>issue-<n>`` finds
        those too, and more than one match is reported rather than guessed.
        """
        stem = f"{prefix}issue-{number}"
        return [
            b for b in self.branches_with_prefix(prefix)
            if b == stem or b.startswith(stem + "-")
        ]

    def commits_between(self, base: str, tip: str) -> int:
        _, out, _ = self.run(["rev-list", "--count", f"{base}..{tip}"])
        return int(out or 0)

    def merges_between(self, base: str, tip: str) -> int:
        _, out, _ = self.run(["rev-list", "--merges", "--count", f"{base}..{tip}"])
        return int(out or 0)

    def is_ancestor(self, maybe_ancestor: str, descendant: str) -> bool:
        code, _, _ = self.run(
            ["merge-base", "--is-ancestor", maybe_ancestor, descendant], check=False
        )
        return code == 0

    def merge_base(self, a: str, b: str) -> Optional[str]:
        code, out, _ = self.run(["merge-base", a, b], check=False)
        return out if code == 0 and out else None

    def authors_between(self, base: str, tip: str) -> List[str]:
        _, out, _ = self.run(
            ["log", "--format=%an <%ae>|%cn <%ce>", f"{base}..{tip}"]
        )
        people: List[str] = []
        for line in out.splitlines():
            people.extend(part.strip() for part in line.split("|") if part.strip())
        return people

    def diff_text(self, base: str, tip: str, max_bytes: int = 4_000_000) -> str:
        _, out, _ = self.run(["diff", "--no-color", f"{base}...{tip}"])
        return out[:max_bytes]

    # ------------------------------------------------------------ changes --

    def fetch(self, remote: str = "origin") -> None:
        self._mutate(f"fetch {remote}")
        self.run(["fetch", "--quiet", "--prune", remote])

    def push_branch(self, branch: str, prefix: str, remote: str = "origin") -> None:
        """Push one agent branch, never with force.

        ``prefix`` is the agent namespace. The coordinator can push, so the
        namespace is the thing that keeps it away from main and away from
        every human branch. The check is here, at the one place that pushes,
        and not at each caller.

        A non-fast-forward push fails. That is the wanted behaviour: the remote
        branch moved, so the local result is not a continuation of it, and a
        human has to look.
        """
        if not branch.startswith(prefix):
            raise GitError(
                f"refusing to push {branch}: it is outside the {prefix} namespace"
            )
        self._mutate(f"push {branch} to {remote}")
        code, out, err = self.run(
            ["push", remote, f"refs/heads/{branch}:refs/heads/{branch}"], check=False
        )
        if code != 0:
            raise GitError(f"cannot push {branch}: {err.strip() or out.strip()}")

    def delete_local_branch(self, branch: str, prefix: str) -> None:
        if not branch.startswith(prefix):
            raise GitError(f"refusing to delete {branch}: it is outside {prefix}")
        self._mutate(f"delete the local branch {branch}")
        self.run(["branch", "-D", branch], check=False)

    # ---------------------------------------------------------- adoption --

    def audit_branch(
        self,
        branch: str,
        base_ref: str,
        max_commits: int,
        allow_merges: bool,
        expected_identities: Sequence[str],
        require_agent_authored: bool,
    ) -> BranchAudit:
        """Decide whether an existing branch may be adopted.

        A matching name proves nothing. Each rule below removes one way a
        branch could hold work that this queue must not push.
        """
        reasons: List[str] = []
        sha = self.rev_parse(branch)
        if not sha:
            return BranchAudit(branch, reasons=("the branch does not name a commit",))

        base_sha = self.rev_parse(base_ref)
        if not base_sha:
            return BranchAudit(branch, sha, reasons=(f"cannot resolve {base_ref}",))

        fork_point = self.merge_base(branch, base_ref)
        if not fork_point:
            reasons.append(f"the branch shares no history with {base_ref}")
        elif not self.is_ancestor(fork_point, base_ref):
            reasons.append(f"the branch did not fork from {base_ref}")

        count = self.commits_between(base_ref, branch)
        if count < 1:
            reasons.append(f"the branch adds no commit over {base_ref}")
        elif count > max_commits:
            reasons.append(f"the branch adds {count} commits, and the limit is {max_commits}")

        if not allow_merges and self.merges_between(base_ref, branch) > 0:
            reasons.append("the branch carries a merge commit")

        if require_agent_authored and count >= 1:
            unexpected = sorted(
                {p for p in self.authors_between(base_ref, branch)
                 if p not in expected_identities}
            )
            if unexpected:
                reasons.append(
                    "the branch carries commits that agentbox did not make: "
                    + ", ".join(unexpected[:3])
                )

        if branch == self.current_branch():
            reasons.append("the branch is the one this working tree has checked out")

        return BranchAudit(branch, sha, count, not reasons, tuple(reasons))


# ----------------------------------------------------------- secret scan --


def scan_text_for_secrets(scanner: str, text: str, timeout: int = 120) -> List[str]:
    """Run bin/scan-secrets over one text, and return its findings.

    The diff of a branch is read before the branch is pushed. A push is
    publication, and a credential that reaches GitHub cannot be recalled by
    deleting the branch.
    """
    proc = subprocess.run(
        [scanner, "--stdin"],
        input=text,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "NO_COLOR": "1"},
    )
    if proc.returncode == 0:
        return []
    return [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.startswith("FINDING")
    ] or [f"scan-secrets exited {proc.returncode}"]
