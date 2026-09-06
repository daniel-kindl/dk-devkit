"""Queue policy: what the coordinator is allowed to do in one repository.

Policy is declarative and it is resolved from files, never from a rule about a
named repository. The workstation rule is that the router and the tools resolve
behaviour generically, so agentqueue does the same.

Resolution order, first match wins per file, and the files overlay:

    1. config/agentqueue/policy.default.json   the built-in policy
    2. <repo>/.agentqueue.json                 tracked with the repository
    3. ~/.config/agentqueue/repos/<slug>.json  machine state, for a repository
                                               that cannot carry the file yet
    4. --config PATH                           an explicit override

Later files overlay earlier ones key by key. ``.agentqueue.json`` is the place
a policy belongs, because the policy is a property of the project.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Dict, List, Optional, Tuple

_MERGE_METHODS = ("squash", "merge", "rebase")
_REVIEW_POLICIES = ("required", "optional", "none")
_DEPENDENCY_SOURCES = ("github", "prose")
_EFFORT_MODES = ("auto", "fixed")


class PolicyError(Exception):
    """The policy is unusable. The coordinator refuses to start."""


@dataclasses.dataclass
class Policy:
    version: int = 1
    baseBranch: str = "main"
    branchPrefix: str = "agent/"

    issueLabel: str = "ready-for-agent"
    inProgressLabel: str = "agent-in-progress"
    humanLabel: str = "ready-for-human"
    failedLabel: str = "agent-failed"

    dependencySources: Tuple[str, ...] = ("github", "prose")

    checks: Tuple[str, ...] = ()

    requiredChecks: Tuple[str, ...] = ()
    requireCiChecks: bool = True
    ciTimeoutSeconds: int = 1800
    ciPollSeconds: int = 20
    ciGraceSeconds: int = 180

    reviewPolicy: str = "optional"
    mergeWithoutReview: bool = False

    autoMerge: bool = False
    mergeMethod: str = "squash"
    deleteRemoteBranchOnMerge: bool = True
    deleteLocalBranchOnMerge: bool = False
    closeIssueIfPullRequestDidNot: bool = False

    # Model routing. The tier catalog holds the pinned model IDs, and
    # lib/agentqueue/effort.py holds the rules. "auto" reads the signals on
    # the issue; "fixed" pins every task in this repository to "effort".
    effortMode: str = "auto"
    effort: str = "standard"
    effortLabelPrefix: str = "effort:"
    escalateEffortOnRetry: bool = True
    modelTiers: str = ""

    maxParallel: int = 1
    maxRetries: int = 2
    maxFixRounds: int = 2
    maxCommits: int = 20
    # One bounded implementation invocation is the normal path. The loop that
    # earns another model invocation is the evidence-driven one: a failing
    # check or a reviewer finding. A larger number here re-introduces a
    # general retry dimension next to maxFixRounds and maxRetries, and the
    # combined budget of three of them is difficult to reason about.
    maxIterations: int = 1
    agentTimeoutSeconds: int = 3600

    # The execution-efficiency budget for ONE model invocation. Sandcastle's
    # idle timeout sees an agent that stops talking, and agentTimeoutSeconds
    # sees a run that takes too long. Neither sees an agent that stays busy
    # and gets nowhere, which is what these bound.
    #
    # A soft limit reports a warning in the compact output and in the run
    # evidence. A hard limit stops the agent and imports nothing. 0 turns one
    # limit off, and each soft limit must stay below its hard limit.
    softBudgetSeconds: int = 600
    hardBudgetSeconds: int = 1200
    softToolCalls: int = 30
    hardToolCalls: int = 60
    staleClaimSeconds: int = 7200

    adoptExistingBranch: bool = True
    adoptExistingPullRequest: bool = True
    requireAgentAuthoredCommits: bool = True

    scanDiffForSecrets: bool = True

    referencedIssueDepth: int = 1
    maxReferencedIssues: int = 6
    maxPromptBytes: int = 60000

    # Where each value came from. The dry run prints it, so a surprising
    # setting can be traced to the file that set it.
    sources: Tuple[str, ...] = ()

    # ------------------------------------------------------------------ --

    def validate(self) -> None:
        """Refuse a policy that cannot be carried out safely."""
        if self.version != 1:
            raise PolicyError(f"unsupported policy version: {self.version}")
        if not self.branchPrefix.endswith("/"):
            raise PolicyError('branchPrefix must end with "/"')
        if self.mergeMethod not in _MERGE_METHODS:
            raise PolicyError(
                f"mergeMethod must be one of {', '.join(_MERGE_METHODS)}"
            )
        if self.reviewPolicy not in _REVIEW_POLICIES:
            raise PolicyError(
                f"reviewPolicy must be one of {', '.join(_REVIEW_POLICIES)}"
            )
        if self.effortMode not in _EFFORT_MODES:
            raise PolicyError(
                f"effortMode must be one of {', '.join(_EFFORT_MODES)}"
            )
        if not self.effort.strip():
            raise PolicyError("effort must name a tier in the model tier catalog")
        if not self.effortLabelPrefix.strip():
            raise PolicyError("effortLabelPrefix must not be empty")
        for source in self.dependencySources:
            if source not in _DEPENDENCY_SOURCES:
                raise PolicyError(f"unknown dependency source: {source}")
        if not self.dependencySources:
            raise PolicyError("dependencySources must name at least one source")
        for name, value in (
            ("maxParallel", self.maxParallel),
            ("maxCommits", self.maxCommits),
            ("maxIterations", self.maxIterations),
        ):
            if value < 1:
                raise PolicyError(f"{name} must be at least 1")
        for name, value in (
            ("maxRetries", self.maxRetries),
            ("maxFixRounds", self.maxFixRounds),
            ("softBudgetSeconds", self.softBudgetSeconds),
            ("hardBudgetSeconds", self.hardBudgetSeconds),
            ("softToolCalls", self.softToolCalls),
            ("hardToolCalls", self.hardToolCalls),
        ):
            if value < 0:
                raise PolicyError(f"{name} must not be negative")
        # A soft limit at or above its hard limit is refused, not clamped. It
        # would mean the warning arrives after the stop, and whoever wrote it
        # believes there is a warning stage when there is none.
        for soft, hard in (
            ("softBudgetSeconds", "hardBudgetSeconds"),
            ("softToolCalls", "hardToolCalls"),
        ):
            soft_value = getattr(self, soft)
            hard_value = getattr(self, hard)
            if hard_value and soft_value and soft_value >= hard_value:
                raise PolicyError(
                    f"{soft} ({soft_value}) must be below {hard} ({hard_value})"
                )
        if self.agentTimeoutSeconds < 60:
            raise PolicyError("agentTimeoutSeconds must be at least 60")
        if self.ciPollSeconds < 1:
            raise PolicyError("ciPollSeconds must be at least 1")
        if self.reviewPolicy == "required" and self.mergeWithoutReview:
            raise PolicyError(
                'reviewPolicy "required" and mergeWithoutReview true contradict '
                "each other. Choose one."
            )
        labels = [
            self.issueLabel,
            self.inProgressLabel,
            self.humanLabel,
            self.failedLabel,
        ]
        if len(set(labels)) != len(labels):
            raise PolicyError("the four lifecycle labels must all differ")

    # ------------------------------------------------------------------ --

    def merge_is_permitted_without_review(self) -> bool:
        """Whether an automatic merge may proceed with no independent review.

        This is an explicit choice, never a fallback. ``reviewPolicy`` says
        whether a review is wanted, and ``mergeWithoutReview`` says what to do
        when it did not happen.
        """
        if self.reviewPolicy == "none":
            return True
        return bool(self.mergeWithoutReview)

    def as_dict(self) -> Dict[str, Any]:
        out = dataclasses.asdict(self)
        for key, value in out.items():
            if isinstance(value, tuple):
                out[key] = list(value)
        return out


_TUPLE_FIELDS = {
    "dependencySources",
    "checks",
    "requiredChecks",
    "sources",
}

_FIELDS = {f.name for f in dataclasses.fields(Policy)}


def repo_slug(owner: str, name: str) -> str:
    """The file name a machine-local policy uses for one repository."""
    return f"{owner}--{name}"


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise PolicyError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{path} must hold a JSON object")
    return data


def overlay(base: Policy, data: Dict[str, Any], origin: str) -> Policy:
    """Return a copy of ``base`` with the keys of ``data`` applied.

    An unknown key is a refusal, not a warning. A typed key that a policy file
    silently ignores is how an operator ends up believing a gate is on when it
    is off.
    """
    values = dataclasses.asdict(base)
    unknown = [
        key
        for key in data
        if key not in _FIELDS and not key.startswith("$")
    ]
    if unknown:
        raise PolicyError(
            f"{origin} sets unknown policy key(s): {', '.join(sorted(unknown))}"
        )
    for key, value in data.items():
        if key.startswith("$"):
            continue
        if key in _TUPLE_FIELDS:
            if not isinstance(value, list):
                raise PolicyError(f"{origin}: {key} must be a list")
            value = tuple(str(item) for item in value)
        values[key] = value
    values["sources"] = tuple(base.sources) + (origin,)
    for key in _TUPLE_FIELDS:
        if isinstance(values.get(key), list):
            values[key] = tuple(values[key])
    try:
        return Policy(**values)
    except TypeError as exc:
        raise PolicyError(f"{origin}: {exc}") from exc


def load(
    repo_root: str,
    default_path: str,
    owner: str = "",
    name: str = "",
    explicit_path: Optional[str] = None,
    home: Optional[str] = None,
) -> Policy:
    """Resolve the policy for one repository, and validate the result."""
    policy = Policy()
    if os.path.isfile(default_path):
        policy = overlay(policy, _read_json(default_path), default_path)

    repo_file = os.path.join(repo_root, ".agentqueue.json")
    if os.path.isfile(repo_file):
        policy = overlay(policy, _read_json(repo_file), repo_file)

    if owner and name:
        base_home = home if home is not None else os.path.expanduser("~")
        local = os.path.join(
            base_home, ".config", "agentqueue", "repos", repo_slug(owner, name) + ".json"
        )
        if os.path.isfile(local):
            policy = overlay(policy, _read_json(local), local)

    if explicit_path:
        if not os.path.isfile(explicit_path):
            raise PolicyError(f"no such policy file: {explicit_path}")
        policy = overlay(policy, _read_json(explicit_path), explicit_path)

    policy.validate()
    return policy


def describe_sources(policy: Policy) -> List[str]:
    return list(policy.sources)
