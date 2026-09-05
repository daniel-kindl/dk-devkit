"""The GitHub access layer.

Every call goes through the ``gh`` CLI, so agentqueue inherits the
authentication the user already set up and stores no token of its own. The
credential never leaves this process: it is not written to a file, it is not
passed to agentbox, and it never reaches a sandbox.

The class is split in two on purpose:

    GitHub          the read and write surface the coordinator uses
    GhTransport     the one place that runs the ``gh`` binary

A test replaces the transport, or replaces the whole class with an in-memory
double that has the same surface. Nothing else in the package knows what a
``gh`` argument list looks like.

Every mutating method calls ``_mutate`` first. In dry-run mode ``_mutate``
raises, so a dry run that tried to change GitHub fails loudly instead of
changing GitHub.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence

from .model import CheckRun, Comment, Issue, PullRequest


class GitHubError(Exception):
    """A GitHub call failed, or returned something this code cannot read."""


class DryRunViolation(Exception):
    """A dry run tried to change durable state. This is a coordinator defect."""


class GhTransport:
    """Runs ``gh`` and returns its exit code and output."""

    def __init__(self, binary: str = "gh", timeout: int = 120):
        self.binary = binary
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, args: Sequence[str], stdin: Optional[str] = None):
        proc = subprocess.run(
            [self.binary, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr


class GitHub:
    """Read and change the GitHub state of one repository."""

    def __init__(
        self,
        owner: str,
        name: str,
        transport: Optional[GhTransport] = None,
        dry_run: bool = False,
    ):
        self.owner = owner
        self.name = name
        self.transport = transport or GhTransport()
        self.dry_run = dry_run
        self.mutations: List[str] = []

    # ---------------------------------------------------------- plumbing --

    @property
    def repo(self) -> str:
        return f"{self.owner}/{self.name}"

    def _mutate(self, description: str) -> None:
        if self.dry_run:
            raise DryRunViolation(f"a dry run tried to: {description}")
        self.mutations.append(description)

    def _api(
        self,
        path: str,
        method: str = "GET",
        fields: Optional[Dict[str, Any]] = None,
        paginate: bool = False,
        allow_status: Sequence[int] = (),
    ):
        args = ["api", "-H", "Accept: application/vnd.github+json"]
        if method != "GET":
            args += ["-X", method]
        if paginate:
            args += ["--paginate", "--slurp"]
        args.append(path)
        stdin = None
        if fields is not None:
            args += ["--input", "-"]
            stdin = json.dumps(fields)

        code, out, err = self.transport.run(args, stdin=stdin)
        if code != 0:
            for status in allow_status:
                if f'"status":"{status}"' in out or f"HTTP {status}" in err:
                    return None
                if f"({status})" in err or f" {status}:" in err:
                    return None
            raise GitHubError(f"gh api {path} failed ({code}): {err.strip() or out.strip()}")
        out = out.strip()
        if not out:
            return None
        try:
            data = json.loads(out)
        except ValueError as exc:
            raise GitHubError(f"gh api {path} returned unreadable JSON: {exc}") from exc
        if paginate and isinstance(data, list):
            flat: List[Any] = []
            for page in data:
                if isinstance(page, list):
                    flat.extend(page)
                else:
                    flat.append(page)
            return flat
        return data

    # --------------------------------------------------------------- read --

    @staticmethod
    def _issue_from_api(raw: Dict[str, Any]) -> Issue:
        return Issue(
            number=int(raw["number"]),
            title=raw.get("title") or "",
            body=raw.get("body") or "",
            state=raw.get("state") or "open",
            labels=tuple(
                label["name"] if isinstance(label, dict) else str(label)
                for label in raw.get("labels", [])
            ),
            url=raw.get("html_url") or "",
        )

    def list_issues(self, label: str) -> List[Issue]:
        """Every OPEN issue that carries ``label``. Pull requests are excluded.

        The issues endpoint returns pull requests as well. A pull request has a
        ``pull_request`` key, and that is the documented way to tell them
        apart.
        """
        raw = self._api(
            f"repos/{self.repo}/issues?state=open&labels={label}&per_page=100",
            paginate=True,
        ) or []
        return [self._issue_from_api(item) for item in raw if "pull_request" not in item]

    def get_issue(self, number: int) -> Issue:
        raw = self._api(f"repos/{self.repo}/issues/{number}")
        if not raw:
            raise GitHubError(f"issue #{number} could not be read")
        return self._issue_from_api(raw)

    def list_comments(self, number: int) -> List[Comment]:
        raw = self._api(
            f"repos/{self.repo}/issues/{number}/comments?per_page=100", paginate=True
        ) or []
        return [
            Comment(
                id=int(item["id"]),
                body=item.get("body") or "",
                author=(item.get("user") or {}).get("login", ""),
                created_at=item.get("created_at") or "",
            )
            for item in raw
        ]

    def blocked_by(self, number: int) -> Optional[List[int]]:
        """The issues GitHub records as blocking ``number``.

        Returns ``None`` when the repository or the account does not have the
        dependency feature. ``None`` means "unknown", and the caller must then
        fall back or fail closed. It does not mean "no blockers".
        """
        raw = self._api(
            f"repos/{self.repo}/issues/{number}/dependencies/blocked_by?per_page=100",
            paginate=True,
            allow_status=(404, 410, 415),
        )
        if raw is None:
            return None
        result = []
        for item in raw:
            repo_url = item.get("repository_url", "")
            if repo_url and not repo_url.endswith(f"/{self.repo}"):
                # A cross-repository blocker cannot be judged from here.
                raise GitHubError(
                    f"issue #{number} is blocked by an issue in another repository: "
                    f"{item.get('html_url', repo_url)}"
                )
            result.append(int(item["number"]))
        return result

    def list_pulls(self, state: str = "open") -> List[PullRequest]:
        raw = self._api(
            f"repos/{self.repo}/pulls?state={state}&per_page=100", paginate=True
        ) or []
        return [self._pull_from_api(item) for item in raw]

    @staticmethod
    def _pull_from_api(raw: Dict[str, Any]) -> PullRequest:
        merged = bool(raw.get("merged_at") or raw.get("merged"))
        state = "MERGED" if merged else str(raw.get("state", "open")).upper()
        mergeable = raw.get("mergeable")
        if mergeable is True:
            mergeable_str = "MERGEABLE"
        elif mergeable is False:
            mergeable_str = "CONFLICTING"
        else:
            mergeable_str = "UNKNOWN"
        return PullRequest(
            number=int(raw["number"]),
            state=state,
            head_ref=(raw.get("head") or {}).get("ref", ""),
            base_ref=(raw.get("base") or {}).get("ref", ""),
            head_sha=(raw.get("head") or {}).get("sha", ""),
            merged=merged,
            mergeable=mergeable_str,
            merge_state_status=str(raw.get("mergeable_state", "unknown")).upper(),
            url=raw.get("html_url") or "",
        )

    def get_pull(self, number: int) -> PullRequest:
        raw = self._api(f"repos/{self.repo}/pulls/{number}")
        if not raw:
            raise GitHubError(f"pull request #{number} could not be read")
        return self._pull_from_api(raw)

    def find_pull_for_branch(self, branch: str) -> Optional[PullRequest]:
        """The newest pull request whose head is ``branch``, open or not."""
        raw = self._api(
            f"repos/{self.repo}/pulls?state=all&head={self.owner}:{branch}&per_page=100",
            paginate=True,
        ) or []
        if not raw:
            return None
        pulls = [self._pull_from_api(item) for item in raw]
        pulls.sort(key=lambda p: p.number)
        for pull in reversed(pulls):
            if pull.state == "OPEN":
                return pull
        return pulls[-1]

    def check_runs(self, sha: str) -> List[CheckRun]:
        """Every check run and every commit status of one commit.

        Both surfaces matter. A GitHub Actions workflow reports check runs. An
        external service often reports a commit status instead, and a merge
        gate that ignored one of them would pass a commit that is not green.
        """
        runs: List[CheckRun] = []
        raw = self._api(
            f"repos/{self.repo}/commits/{sha}/check-runs?per_page=100", paginate=True
        ) or []
        for page in raw if isinstance(raw, list) else [raw]:
            for item in page.get("check_runs", []) if isinstance(page, dict) else []:
                runs.append(
                    CheckRun(
                        name=item.get("name", ""),
                        status=item.get("status", "queued"),
                        conclusion=item.get("conclusion") or "",
                    )
                )
        status = self._api(f"repos/{self.repo}/commits/{sha}/status")
        for item in (status or {}).get("statuses", []):
            state = item.get("state", "pending")
            runs.append(
                CheckRun(
                    name=item.get("context", ""),
                    status="completed" if state != "pending" else "in_progress",
                    conclusion={"success": "success", "failure": "failure",
                                "error": "failure"}.get(state, ""),
                )
            )
        return runs

    def failing_run_log(self, sha: str, max_bytes: int = 12000) -> str:
        """The tail of the failed job logs of one commit.

        The log is the only useful input for a repair attempt. It is bounded,
        because a full Actions log is far larger than a prompt should be.
        """
        code, out, _ = self.transport.run(
            ["run", "list", "--repo", self.repo, "--commit", sha,
             "--limit", "10", "--json", "databaseId,conclusion,name"]
        )
        if code != 0 or not out.strip():
            return ""
        try:
            entries = json.loads(out)
        except ValueError:
            return ""
        chunks: List[str] = []
        for entry in entries:
            if entry.get("conclusion") not in ("failure", "timed_out", "cancelled"):
                continue
            code, log, _ = self.transport.run(
                ["run", "view", str(entry["databaseId"]), "--repo", self.repo,
                 "--log-failed"]
            )
            if code == 0 and log.strip():
                chunks.append(f"### {entry.get('name', 'job')}\n{log.strip()}")
        text = "\n\n".join(chunks)
        if len(text) > max_bytes:
            text = "... (earlier output removed)\n" + text[-max_bytes:]
        return text

    # -------------------------------------------------------------- write --

    def add_label(self, number: int, label: str) -> None:
        self._mutate(f"add label {label} to issue #{number}")
        self._api(
            f"repos/{self.repo}/issues/{number}/labels",
            method="POST",
            fields={"labels": [label]},
        )

    def remove_label(self, number: int, label: str) -> None:
        self._mutate(f"remove label {label} from issue #{number}")
        self._api(
            f"repos/{self.repo}/issues/{number}/labels/{label}",
            method="DELETE",
            allow_status=(404,),
        )

    def create_comment(self, number: int, body: str) -> int:
        self._mutate(f"comment on issue #{number}")
        raw = self._api(
            f"repos/{self.repo}/issues/{number}/comments",
            method="POST",
            fields={"body": body},
        )
        return int((raw or {}).get("id", 0))

    def delete_comment(self, comment_id: int) -> None:
        self._mutate(f"delete comment {comment_id}")
        self._api(
            f"repos/{self.repo}/issues/comments/{comment_id}",
            method="DELETE",
            allow_status=(404,),
        )

    def close_issue(self, number: int) -> None:
        self._mutate(f"close issue #{number}")
        self._api(
            f"repos/{self.repo}/issues/{number}",
            method="PATCH",
            fields={"state": "closed"},
        )

    def create_pull(self, title: str, body: str, head: str, base: str) -> PullRequest:
        self._mutate(f"open a pull request for {head}")
        raw = self._api(
            f"repos/{self.repo}/pulls",
            method="POST",
            fields={"title": title, "body": body, "head": head, "base": base},
        )
        if not raw:
            raise GitHubError("the pull request was not created")
        return self._pull_from_api(raw)

    def update_pull_body(self, number: int, body: str) -> None:
        self._mutate(f"update the body of pull request #{number}")
        self._api(
            f"repos/{self.repo}/pulls/{number}",
            method="PATCH",
            fields={"body": body},
        )

    def merge_pull(self, number: int, method: str, expected_sha: str) -> Dict[str, Any]:
        """Merge one pull request, and refuse if its head moved.

        ``sha`` in the merge request is a compare-and-swap. GitHub refuses the
        merge when the head is not that commit, so a push that arrives between
        the last gate and the merge cannot be merged by accident.
        """
        self._mutate(f"merge pull request #{number}")
        return self._api(
            f"repos/{self.repo}/pulls/{number}/merge",
            method="PUT",
            fields={"merge_method": method, "sha": expected_sha},
        ) or {}

    def delete_branch(self, branch: str, prefix: str = "agent/") -> None:
        # The coordinator deletes a merged head branch. Nothing else. A
        # namespace check here is what keeps a defect from reaching main.
        if not branch.startswith(prefix):
            raise GitHubError(
                f"refusing to delete {branch}: it is outside the {prefix} namespace"
            )
        self._mutate(f"delete the remote branch {branch}")
        self._api(
            f"repos/{self.repo}/git/refs/heads/{branch}",
            method="DELETE",
            allow_status=(404, 422),
        )
