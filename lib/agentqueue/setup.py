"""Enroll ONE repository with agentq, and start no work.

Installing the coordinator and preparing a repository are two operations.
``./install.sh --components agentq`` puts the command on the machine. This
module answers the next question: is THIS repository ready for a run, and what
does a human still have to decide?

The module reports. It changes exactly one thing, and only when it is asked
to: ``--write-policy`` writes the repository policy file. It never labels an
issue, never pushes, never merges, and never converges the label taxonomy of
the repository. Label drift is reported with the ``repo-labels`` command that
repairs it, because deleting a label removes it from every issue and pull
request, and that is a decision for a human.

Every finding carries one of four states:

    ok      the repository already satisfies this
    gap     a run would be blocked or unsafe until a human acts
    action  a suggestion; the run works without it
    note    evidence, so a surprising setting can be traced

The report is ready when it holds no gap. Nothing here guesses an unsafe
policy: automatic merge and review bypass stay off unless a human turns them
on in the policy file.
"""

from __future__ import annotations

import dataclasses
import glob
import json
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

OK = "ok"
GAP = "gap"
ACTION = "action"
NOTE = "note"

_MARKERS = {OK: "ok  ", GAP: "GAP ", ACTION: "todo", NOTE: "    "}

# The group in manifests/github-labels.json that holds the labels the agent
# lifecycle depends on. The catalog is the source of truth for their colors
# and descriptions; this module only reads it.
WORKFLOW_GROUP = "agent-workflow"


class SetupError(Exception):
    """The repository cannot be inspected. Nothing was changed."""


@dataclasses.dataclass(frozen=True)
class Finding:
    key: str
    title: str
    state: str
    detail: str
    remedy: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "state": self.state,
            "detail": self.detail,
            "remedy": self.remedy,
        }


@dataclasses.dataclass
class Report:
    repository: str
    root: str
    findings: Tuple[Finding, ...] = ()

    @property
    def gaps(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.state == GAP)

    @property
    def actions(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.state == ACTION)

    @property
    def ready(self) -> bool:
        return not self.gaps

    def as_dict(self) -> Dict[str, Any]:
        return {
            "repository": self.repository,
            "root": self.root,
            "ready": self.ready,
            "findings": [f.as_dict() for f in self.findings],
        }


# ------------------------------------------------------------- detection --


@dataclasses.dataclass(frozen=True)
class CheckSuggestion:
    """Deterministic local checks this repository already declares."""

    commands: Tuple[str, ...]
    evidence: str


def _package_scripts(repo_root: str) -> Dict[str, str]:
    path = os.path.join(repo_root, "package.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def detect_checks(repo_root: str) -> CheckSuggestion:
    """The checks a run should execute, from evidence in the repository.

    A suggestion is made only when the evidence is unambiguous: a lockfile
    names the package manager, and a script of that name exists. A repository
    that gives no such evidence gets no suggestion, because a wrong check
    command turns every task into a failed one.
    """
    scripts = _package_scripts(repo_root)
    managers = (
        ("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm"),
        ("package-lock.json", "npm ci", "npm run"),
        ("yarn.lock", "yarn install --immutable", "yarn"),
    )
    for lockfile, install, prefix in managers:
        if not os.path.exists(os.path.join(repo_root, lockfile)):
            continue
        for script in ("check", "test"):
            if script in scripts:
                return CheckSuggestion(
                    (install, f"{prefix} {script}".strip()),
                    f"{lockfile} and the \"{script}\" script in package.json",
                )
        return CheckSuggestion((install,), f"{lockfile}, with no check script")

    verify = os.path.join(repo_root, "verify.sh")
    if os.access(verify, os.X_OK):
        return CheckSuggestion(("./verify.sh",), "the executable verify.sh")

    return CheckSuggestion((), "no lockfile and no verify.sh")


def detect_workflows(repo_root: str) -> Tuple[str, ...]:
    """The GitHub Actions workflow files this repository holds."""
    found: List[str] = []
    for pattern in ("*.yml", "*.yaml"):
        found += glob.glob(os.path.join(repo_root, ".github", "workflows", pattern))
    return tuple(sorted(os.path.basename(path) for path in found))


def workflow_labels(install_root: str) -> Tuple[Dict[str, str], ...]:
    """The canonical agent-workflow labels, from the label catalog.

    The catalog in ``manifests/github-labels.json`` is the source of truth,
    and ``repo-labels`` is the tool that applies it. Reading the same file
    here keeps the two from drifting apart.
    """
    path = os.path.join(install_root, "manifests", "github-labels.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SetupError(f"the label catalog could not be read: {exc}") from exc
    labels = data.get("labels")
    if not isinstance(labels, list):
        raise SetupError(f"{path} holds no label list")
    return tuple(
        {
            "name": str(item.get("name", "")),
            "color": str(item.get("color", "")).lower(),
            "description": str(item.get("description", "")),
        }
        for item in labels
        if isinstance(item, dict) and item.get("group") == WORKFLOW_GROUP
    )


def label_drift(
    desired: Sequence[Dict[str, str]],
    lifecycle: Sequence[str],
    current: Sequence[Dict[str, str]],
) -> Tuple[str, ...]:
    """What separates the repository labels from the ones a run depends on.

    Two different demands are checked. A label in the canonical catalog must
    match its color and description exactly, because the catalog owns it. A
    lifecycle label that the policy renamed is only required to exist, because
    the catalog says nothing about a name a repository chose for itself.

    An extra label is not drift here. Only ``repo-labels`` decides what is
    obsolete, and only a human confirms a delete.
    """
    have = {item["name"]: item for item in current}
    problems: List[str] = []
    named = {item["name"] for item in desired}

    for want in desired:
        got = have.get(want["name"])
        if got is None:
            problems.append(f"{want['name']}: missing")
            continue
        if got.get("color", "").lower() != want["color"]:
            problems.append(
                f"{want['name']}: color {got.get('color', '')} "
                f"(catalog says {want['color']})"
            )
        if got.get("description", "") != want["description"]:
            problems.append(f"{want['name']}: description differs from the catalog")

    for name in lifecycle:
        if name in named:
            continue
        if name not in have:
            problems.append(f"{name}: missing (this policy renamed a lifecycle label)")

    return tuple(problems)


# --------------------------------------------------------------- report --


def policy_draft(pol, base_branch: str, checks: Sequence[str]) -> Dict[str, Any]:
    """The policy file a new repository starts from.

    The detected values fill in the two fields that are repository facts: the
    base branch and the local checks. Every gate stays closed. A merge without
    a human is a decision, so ``autoMerge`` is false here and stays false
    until somebody sets it.
    """
    return {
        "version": 1,
        "baseBranch": base_branch or pol.baseBranch,
        "issueLabel": pol.issueLabel,
        "checks": list(checks),
        "requiredChecks": [],
        "reviewPolicy": "optional",
        "mergeWithoutReview": False,
        "autoMerge": False,
        "mergeMethod": "squash",
        "maxParallel": 1,
        "maxRetries": 2,
    }


def inspect(
    repo_root: str,
    owner: str,
    name: str,
    pol,
    install_root: str,
    *,
    git=None,
    read_default_branch: Optional[Callable[[], str]] = None,
    read_labels: Optional[Callable[[], List[Dict[str, str]]]] = None,
    gh_ready: Optional[bool] = None,
    ssh_agent: str = "",
    agentbox: str = "",
) -> Report:
    """Everything ``agentq setup`` knows about one repository.

    Each reader is injected, so this function stays deterministic and a test
    needs no network. A reader that is absent, or that fails, produces a
    finding that says the state is unknown. Unknown is never reported as ok.
    """
    slug = f"{owner}/{name}"
    findings: List[Finding] = []

    findings.append(Finding(
        "repository", "repository", NOTE, f"{slug}  ({repo_root})",
    ))

    # --- the policy file ---------------------------------------------------
    repo_policy = os.path.join(repo_root, ".agentqueue.json")
    # The built-in default is always one source. It is not repository policy,
    # so a repository whose only source is that file has no policy of its own.
    builtin = os.path.join(
        install_root, "config", "agentqueue", "policy.default.json"
    )
    tracked = [s for s in pol.sources if s not in (builtin, repo_policy)]
    if os.path.isfile(repo_policy):
        findings.append(Finding(
            "policy", "policy file", OK, repo_policy,
        ))
    elif tracked:
        findings.append(Finding(
            "policy", "policy file", OK,
            "outside the repository: " + ", ".join(tracked),
        ))
    else:
        findings.append(Finding(
            "policy", "policy file", ACTION,
            "none; the built-in default would be used",
            "agentq setup --write-policy",
        ))

    # --- the base branch ---------------------------------------------------
    remote_default = ""
    if read_default_branch is not None:
        try:
            remote_default = read_default_branch()
        except Exception as exc:  # a transport failure is evidence, not a crash
            findings.append(Finding(
                "base-branch", "base branch", GAP,
                f"GitHub could not be read: {exc}",
                "gh auth status",
            ))
    if read_default_branch is None:
        findings.append(Finding(
            "base-branch", "base branch", NOTE,
            f"{pol.baseBranch} (the GitHub default was not read)",
        ))
    elif remote_default and remote_default != pol.baseBranch:
        findings.append(Finding(
            "base-branch", "base branch", GAP,
            f"the policy says {pol.baseBranch}, GitHub says {remote_default}",
            f'set "baseBranch": "{remote_default}" in the policy, or change the '
            "default branch on GitHub",
        ))
    elif remote_default:
        findings.append(Finding(
            "base-branch", "base branch", OK, remote_default,
        ))
    elif not any(f.key == "base-branch" for f in findings):
        # The read returned nothing: the repository is not there, or this
        # account cannot see it. Either way a run cannot work, and an absent
        # finding would read as an answer that was never given.
        findings.append(Finding(
            "base-branch", "base branch", GAP,
            f"GitHub named no default branch for {slug}",
            "check the repository name and what this gh account can read",
        ))

    if git is not None:
        ref = f"refs/remotes/origin/{pol.baseBranch}"
        try:
            present = bool(git.rev_parse(ref))
        except Exception:
            present = False
        if present:
            findings.append(Finding(
                "base-ref", "origin/" + pol.baseBranch, OK, "fetched",
            ))
        else:
            findings.append(Finding(
                "base-ref", "origin/" + pol.baseBranch, GAP,
                "the remote-tracking branch is missing",
                "git fetch origin",
            ))

    # --- the local checks --------------------------------------------------
    suggestion = detect_checks(repo_root)
    if pol.checks:
        findings.append(Finding(
            "checks", "local checks", OK, ", ".join(pol.checks),
        ))
    elif suggestion.commands:
        findings.append(Finding(
            "checks", "local checks", ACTION,
            "none in the policy; this repository suggests "
            + ", ".join(suggestion.commands)
            + f"  (from {suggestion.evidence})",
            'add them to "checks" in the policy file',
        ))
    else:
        findings.append(Finding(
            "checks", "local checks", ACTION,
            f"none, and none could be detected ({suggestion.evidence})",
            'add the commands that prove a change is good to "checks"',
        ))

    # --- the checks GitHub runs -------------------------------------------
    workflows = detect_workflows(repo_root)
    if workflows:
        findings.append(Finding(
            "ci", "GitHub checks", OK, ", ".join(workflows),
        ))
    elif pol.requiredChecks:
        findings.append(Finding(
            "ci", "GitHub checks", GAP,
            "requiredChecks names "
            + ", ".join(pol.requiredChecks)
            + ", and this repository holds no workflow file",
            "add the workflow, or empty requiredChecks",
        ))
    else:
        findings.append(Finding(
            "ci", "GitHub checks", NOTE,
            "no workflow file; a run waits "
            f"{pol.ciGraceSeconds}s and then treats the absence as undecided",
        ))

    # --- the labels a run depends on --------------------------------------
    lifecycle = (pol.issueLabel, pol.inProgressLabel, pol.humanLabel, pol.failedLabel)
    if read_labels is None:
        findings.append(Finding(
            "labels", "workflow labels", NOTE,
            "not read; " + ", ".join(lifecycle) + " must exist",
            f"repo-labels check --repo {slug}",
        ))
    else:
        try:
            current = read_labels()
        except Exception as exc:
            findings.append(Finding(
                "labels", "workflow labels", GAP,
                f"the repository labels could not be read: {exc}",
                f"repo-labels check --repo {slug}",
            ))
        else:
            drift = label_drift(workflow_labels(install_root), lifecycle, current)
            if drift:
                findings.append(Finding(
                    "labels", "workflow labels", GAP,
                    "; ".join(drift),
                    f"repo-labels sync --repo {slug}   (it deletes obsolete "
                    "labels; read repo-labels check first)",
                ))
            else:
                findings.append(Finding(
                    "labels", "workflow labels", OK,
                    "every workflow label matches the catalog",
                ))

    # --- the authority this side holds ------------------------------------
    if gh_ready is None:
        findings.append(Finding("auth", "gh", NOTE, "not checked"))
    elif gh_ready:
        findings.append(Finding("auth", "gh", OK, "present and authenticated"))
    else:
        findings.append(Finding(
            "auth", "gh", GAP, "absent, or not authenticated",
            "gh auth login --git-protocol ssh",
        ))

    if ssh_agent:
        findings.append(Finding("ssh", "ssh-agent", OK, "forwarded"))
    else:
        findings.append(Finding(
            "ssh", "ssh-agent", GAP, "not forwarded; a push would fail",
            "start the coordinator from a terminal that forwards SSH_AUTH_SOCK",
        ))

    if agentbox:
        executable = os.access(agentbox, os.X_OK)
        findings.append(Finding(
            "agentbox", "agentbox", OK if executable else GAP,
            agentbox if executable else f"{agentbox} is not executable",
            "" if executable else "./install.sh --components agentbox",
        ))

    # --- what stays a human decision --------------------------------------
    findings.append(Finding(
        "gates", "merge gates", NOTE,
        f"autoMerge {pol.autoMerge}, reviewPolicy {pol.reviewPolicy}, "
        f"merge without review {pol.merge_is_permitted_without_review()}",
    ))

    return Report(slug, repo_root, tuple(findings))


def render(report: Report) -> List[str]:
    """The report as lines for a terminal."""
    width = max((len(f.title) for f in report.findings), default=0)
    lines = ["agentq setup\n"]
    for finding in report.findings:
        lines.append(
            f"  {_MARKERS[finding.state]}  {finding.title.ljust(width)}  "
            f"{finding.detail}"
        )
        if finding.remedy:
            lines.append(f"        {' ' * width}  -> {finding.remedy}")
    lines.append("")
    if report.ready:
        lines.append("this repository is ready: agentq plan, then agentq run")
    else:
        lines.append(
            f"{len(report.gaps)} gap(s) block a run. "
            "agentq changed nothing; each one is a human decision."
        )
    if report.actions:
        lines.append(f"{len(report.actions)} suggestion(s) above are optional.")
    return lines
