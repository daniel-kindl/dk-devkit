"""Build every text that leaves the coordinator.

Three readers, two registers.

    the implementer agent   Strict controlled English. One instruction per
                            sentence, active voice, no phrasal verb. The agent
                            has no human to ask, so a second reading must not
                            exist.
    the repair agent        the same register, plus the failure evidence.
    a human on GitHub       the pull request body and the issue comments.

The user never writes a prompt file. Everything the implementer needs comes
from GitHub, and the coordinator is allowed to read GitHub because it is the
trusted half.

Nothing in a prompt names a credential, a credential path, or a run directory.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

from .model import Comment, Issue

_ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")
_FENCE = re.compile(r"```.*?```", re.DOTALL)

# Comments the coordinator itself wrote. Feeding them back would teach the
# agent about the queue instead of about the work.
_OWN_MARKERS = ("<!-- agentqueue:claim", "<!-- agentqueue:release")


def referenced_issues(body: str, exclude: Iterable[int] = ()) -> List[int]:
    """The issues an issue body points at, in first-seen order.

    A specification or a decision usually lives in another issue, and the
    implementer cannot open a browser. The referenced issues are therefore
    fetched and quoted in the prompt.
    """
    skip = set(exclude)
    seen: List[int] = []
    for match in _ISSUE_REF.finditer(_FENCE.sub(" ", body or "")):
        number = int(match.group(1))
        if number in skip or number in seen:
            continue
        seen.append(number)
    return seen


def acceptance_criteria(body: str) -> List[str]:
    """The checklist items under an "Acceptance" heading, if there is one."""
    lines = (body or "").splitlines()
    out: List[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            inside = "acceptance" in stripped.lower()
            continue
        if inside and re.match(r"^[-*] \[[ xX]\]\s+", stripped):
            out.append(re.sub(r"^[-*] \[[ xX]\]\s+", "", stripped))
    if out:
        return out
    return [
        re.sub(r"^[-*] \[[ xX]\]\s+", "", line.strip())
        for line in lines
        if re.match(r"^\s*[-*] \[[ xX]\]\s+", line)
    ]


def _quote_issue(issue: Issue, comments: Sequence[Comment], comment_limit: int) -> str:
    parts = [f"### Issue #{issue.number}: {issue.title}", "", issue.body.strip(), ""]
    kept = [c for c in comments if not any(m in c.body for m in _OWN_MARKERS)]
    for comment in kept[-comment_limit:] if comment_limit else []:
        parts += [f"#### Comment by {comment.author or 'someone'}", "",
                  comment.body.strip(), ""]
    return "\n".join(parts)


def implementation_prompt(
    issue: Issue,
    comments: Sequence[Comment],
    referenced: Sequence[tuple],
    base_commit: str,
    checks: Sequence[str],
    max_bytes: int = 60000,
) -> str:
    """The instruction the sandbox agent receives.

    ``referenced`` holds ``(Issue, [Comment])`` pairs for the specification and
    decision issues that this issue names.
    """
    criteria = acceptance_criteria(issue.body)
    check_lines = "\n".join(f"    {c}" for c in checks) or "    (none configured)"
    criteria_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria)) or (
        "The issue states no checklist. Use the Scope section as the criteria."
    )

    head = f"""# Task: implement issue #{issue.number}

You work in a disposable clone of the repository. The clone starts at commit
{base_commit[:12]}. Commit your work in this clone. Do not push. Do not open a
pull request. You hold no GitHub credential, so those commands fail.

## What to do

1. Read `AGENTS.md` in the repository root. Obey it.
2. Read the documents that `AGENTS.md` names, if your change touches them.
3. Implement issue #{issue.number} below. Implement that issue only.
4. Run the repository checks after each change. The list is below.
5. Repair every failure the checks report. Repeat step 4 until the checks pass.
6. Commit the result with a clear message.

## Limits

Implement what the issue states. Add nothing the issue does not state.
Do not change an unrelated file. Do not change the build configuration unless
the issue asks for it. Do not add a dependency unless the issue asks for it.
Do not weaken a test to make it pass.

Ask no question. No human reads your output during this run.

## Repository checks

The coordinator runs these commands in this sandbox after you stop:

{check_lines}

Run them yourself first. A check that fails after you stop costs a whole new
run.

## Acceptance criteria

{criteria_lines}

## The issue

"""
    body = [head, _quote_issue(issue, comments, comment_limit=8)]

    if referenced:
        body.append("## Referenced issues\n")
        body.append(
            "These issues hold the specification and the decisions. They are "
            "context. Implement none of them.\n"
        )
        for other, other_comments in referenced:
            body.append(_quote_issue(other, other_comments, comment_limit=2))

    text = "\n".join(body)
    if len(text) > max_bytes:
        text = text[:max_bytes] + "\n\n(The rest was removed because of a size limit.)\n"
    return text


def repair_prompt(
    issue: Issue,
    branch: str,
    failures: Sequence[str],
    evidence: str,
    checks: Sequence[str],
    attempt: int,
    max_bytes: int = 40000,
) -> str:
    """The instruction for a repair run after a check failed.

    The evidence is the failing check name and the tail of its output. It is
    bounded, because a full log is longer than a prompt should be.
    """
    failure_lines = "\n".join(f"    {f}" for f in failures) or "    (not reported)"
    check_lines = "\n".join(f"    {c}" for c in checks) or "    (none configured)"
    text = f"""# Task: repair the failing checks on {branch}

The implementation of issue #{issue.number} is on this branch. The checks
failed. This is repair attempt {attempt}.

## What to do

1. Read the failure evidence below.
2. Find the cause. Fix the cause.
3. Run the repository checks. Repeat until they pass.
4. Commit the fix on this branch.

## Limits

Fix the failure. Change nothing else. Do not delete a test. Do not weaken a
test. Do not mark a test as skipped to make the run green.

If the failure is not caused by the change on this branch, say so in the
commit message and stop.

## The checks that must pass

{check_lines}

## What failed

{failure_lines}

## Evidence

```
{evidence.strip()[:max_bytes]}
```
"""
    return text


# ---------------------------------------------------------- pull requests --


def pull_request_title(issue: Issue, prefix: str = "") -> str:
    title = issue.title.strip()
    # An issue title often starts with the verb the commit wants anyway.
    return f"{prefix}{title}" if prefix else title


def pull_request_body(
    issue: Issue,
    run_id: str,
    base_commit: str,
    checks: Sequence[str],
    checks_passed: Optional[bool],
    review: Dict[str, object],
    fix_rounds: int,
    adopted: str = "",
) -> str:
    """The pull request body.

    Two rules govern it. It states exactly what ran, and it claims nothing
    that did not run. It names no credential and no run directory.
    """
    if not checks:
        check_text = "No deterministic check was configured for this repository."
    elif checks_passed is True:
        check_text = "All deterministic checks passed in the sandbox:\n" + "\n".join(
            f"- `{c}`" for c in checks
        )
    elif checks_passed is False:
        check_text = "Deterministic checks FAILED in the sandbox:\n" + "\n".join(
            f"- `{c}`" for c in checks
        )
    else:
        check_text = (
            "The deterministic checks were configured, but the run stopped "
            "before they reported."
        )

    if review.get("ran"):
        review_text = (
            f"An independent reviewer ({review.get('agent', 'unknown')}) ran and "
            "left its result on this branch."
        )
    else:
        review_text = (
            "No independent model review ran. Reason: "
            f"{review.get('reason', 'not configured')}. The repository policy "
            "allows a merge on the deterministic checks and the GitHub checks "
            "alone."
        )

    adopted_text = f"\n**Adopted existing work:** {adopted}\n" if adopted else ""
    fix_text = (
        f"\nThe sandbox ran {fix_rounds} repair round(s) against its own checks "
        "before it finished.\n"
        if fix_rounds
        else ""
    )

    return f"""Closes #{issue.number}

## What this is

An unattended implementation of issue #{issue.number}, produced by `agentbox`
and delivered by `agentqueue`.

The agent worked in a disposable clone inside a sandbox. It held no GitHub
credential, no SSH key and no Podman socket. It could not push this branch and
it could not open this pull request. The trusted coordinator did both, after
it validated the imported commits.
{adopted_text}{fix_text}
## Verification

{check_text}

{review_text}

The GitHub checks of this pull request are the gate that decides the merge.

## Provenance

- agentqueue run `{run_id}`
- base commit `{base_commit[:12]}`
- every commit is authored by the neutral sandbox identity, not by a person

See `docs/agentqueue.md` in the workstation repository for the pipeline.
"""


def needs_human_comment(run_id: str, reason: str, detail: str) -> str:
    return f"""**agentqueue** stopped work on this issue and asks for a human.

**Reason:** {reason}

{detail}

The queue continues with other issues. Remove the label this comment added
when the issue is ready for another unattended attempt.

_agentqueue run `{run_id}`_
"""
