"""Which issues are runnable, in which order.

The label says an issue is specified well enough for an implementation agent.
It does not say the issue can start. An issue is runnable only when all of
this holds:

    the issue is open
    AND it carries the ready label
    AND no live claim holds it
    AND it does not ask for a human
    AND every blocker is satisfied

"Satisfied" means the blocking issue is closed. Where the dependency state
cannot be established, the answer is AMBIGUOUS and the issue does not start.
Failing closed is the rule: a wrong "runnable" costs a wrong merge, and a
wrong "blocked" costs a delay.

Two dependency sources, in this order:

    github   the native issue dependency graph, through the REST API. It is
             authoritative when the API answers.
    prose    the repository convention, for example "Blocked by ... #85" in
             the issue body. It is the documented fallback for a repository
             whose dependencies are not recorded natively.

Prose is also read when the native source answered, and any issue it names is
added to the blocker set. That can only make the answer more conservative.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .model import Issue, Runnability, Verdict

# A fenced code block often shows an example that names an issue. It is not a
# dependency statement, so it is removed before the body is read.
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")

# The phrases the repository convention uses. Each one must sit on the same
# line as the issue number it refers to.
_BLOCKER_PHRASES = (
    "blocked by",
    "blocked-by",
    "blocks on",
    "depends on",
    "depends upon",
    "dependent on",
    "dependency:",
    "dependencies:",
)

_SAME_REPO_REF = re.compile(r"(?<![\w/])#(\d+)\b")
_CROSS_REPO_REF = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


class ProseBlockers:
    """What the issue body says about its own blockers."""

    def __init__(self, numbers: Sequence[int], ambiguous: bool, notes: Sequence[str]):
        self.numbers: Tuple[int, ...] = tuple(sorted(set(numbers)))
        self.ambiguous = ambiguous
        self.notes: Tuple[str, ...] = tuple(notes)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProseBlockers({self.numbers}, ambiguous={self.ambiguous})"


def parse_prose_blockers(body: str) -> ProseBlockers:
    """Read the blocker statements out of one issue body.

    A line that states a blocker and names no issue in this repository is
    ambiguous. The caller decides what to do with that, and the safe answer is
    to refuse to start.
    """
    text = _INLINE_CODE.sub(" ", _FENCE.sub(" ", body or ""))
    numbers: List[int] = []
    notes: List[str] = []
    ambiguous = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not any(phrase in lowered for phrase in _BLOCKER_PHRASES):
            continue
        cross = _CROSS_REPO_REF.findall(line)
        if cross:
            ambiguous = True
            notes.append(
                "a blocker in another repository: "
                + ", ".join(f"{repo}#{num}" for repo, num in cross)
            )
            continue
        found = [int(n) for n in _SAME_REPO_REF.findall(line)]
        if found:
            numbers.extend(found)
        else:
            ambiguous = True
            notes.append(f'a blocker statement names no issue: "{line[:110]}"')
    return ProseBlockers(numbers, ambiguous, notes)


class DependencyResolver:
    """Answer "what blocks this issue" for every issue the queue considers."""

    def __init__(
        self,
        sources: Sequence[str],
        blocked_by: Callable[[int], Optional[List[int]]],
        get_issue: Callable[[int], Issue],
    ):
        self.sources = tuple(sources)
        self._blocked_by = blocked_by
        self._get_issue = get_issue
        self._issue_cache: Dict[int, Issue] = {}
        self.native_available: Optional[bool] = None

    # -------------------------------------------------------------- issues --

    def issue(self, number: int) -> Issue:
        if number not in self._issue_cache:
            self._issue_cache[number] = self._get_issue(number)
        return self._issue_cache[number]

    def prime(self, issues: Iterable[Issue]) -> None:
        for item in issues:
            self._issue_cache[item.number] = item

    # -------------------------------------------------------- the blockers --

    def blockers_of(self, issue: Issue) -> Tuple[Tuple[int, ...], bool, Tuple[str, ...]]:
        """Return ``(blockers, ambiguous, notes)`` for one issue."""
        blockers: Set[int] = set()
        notes: List[str] = []
        ambiguous = False
        native: Optional[List[int]] = None

        if "github" in self.sources:
            try:
                native = self._blocked_by(issue.number)
            except Exception as exc:  # a failed query is not an empty answer
                return (), True, (f"the dependency API could not be read: {exc}",)
            if native is None:
                self.native_available = False
                notes.append("the GitHub dependency API is not available here")
            else:
                self.native_available = True
                blockers.update(native)

        prose = ProseBlockers((), False, ())
        if "prose" in self.sources:
            prose = parse_prose_blockers(issue.body)
            blockers.update(prose.numbers)
            notes.extend(prose.notes)

        # An unnumbered blocker statement only forces a refusal when nothing
        # else established the dependency. When the native graph named a
        # blocker, the prose is describing the same thing in words.
        if prose.ambiguous and not blockers:
            ambiguous = True
        if native is None and "github" in self.sources and "prose" not in self.sources:
            ambiguous = True

        blockers.discard(issue.number)
        return tuple(sorted(blockers)), ambiguous, tuple(notes)


def find_cycles(graph: Dict[int, Sequence[int]]) -> List[List[int]]:
    """Every dependency cycle in ``graph``, as a list of node lists.

    A cycle can never be satisfied, so every issue on one is reported and none
    of them starts. Reporting beats looping.
    """
    cycles: List[List[int]] = []
    seen_signatures: Set[Tuple[int, ...]] = set()
    state: Dict[int, int] = {}  # 0 unvisited, 1 on the stack, 2 finished
    stack: List[int] = []

    def visit(node: int) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):  # a node with no entry has no edges
            if state.get(nxt, 0) == 0:
                visit(nxt)
            elif state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):]
                signature = tuple(sorted(cycle))
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    cycles.append(list(cycle))
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


class Scheduler:
    """Turn the backlog into an ordered list of runnable issues."""

    def __init__(self, policy, resolver: DependencyResolver, claims):
        self.policy = policy
        self.resolver = resolver
        self.claims = claims

    def evaluate(self, candidates: Sequence[Issue]) -> List[Verdict]:
        """One verdict per candidate, in issue-number order.

        The verdicts are the dry-run output and the scheduler input. Both read
        the same function, so a dry run cannot disagree with a real run.
        """
        self.resolver.prime(candidates)
        verdicts: Dict[int, Verdict] = {}
        graph: Dict[int, Tuple[int, ...]] = {}
        ambiguity: Dict[int, Tuple[bool, Tuple[str, ...]]] = {}

        for issue in candidates:
            blockers, ambiguous, notes = self.resolver.blockers_of(issue)
            graph[issue.number] = blockers
            ambiguity[issue.number] = (ambiguous, notes)

        # A blocker outside the candidate set still takes part in the graph,
        # because a cycle can run through an issue that carries no label.
        frontier = [n for blockers in graph.values() for n in blockers if n not in graph]
        while frontier:
            number = frontier.pop()
            if number in graph:
                continue
            try:
                other = self.resolver.issue(number)
            except Exception:
                graph[number] = ()
                continue
            blockers, _, _ = self.resolver.blockers_of(other)
            graph[number] = blockers
            frontier.extend(n for n in blockers if n not in graph)

        in_cycle: Set[int] = set()
        cycles = find_cycles(graph)
        for cycle in cycles:
            in_cycle.update(cycle)
        self.cycles = cycles

        for issue in candidates:
            verdicts[issue.number] = self._verdict(issue, graph, ambiguity, in_cycle)
        return [verdicts[n] for n in sorted(verdicts)]

    def _verdict(self, issue, graph, ambiguity, in_cycle) -> Verdict:
        policy = self.policy
        if not issue.is_open:
            return Verdict(issue.number, Runnability.INELIGIBLE, "the issue is closed")
        if not issue.has_label(policy.issueLabel):
            return Verdict(
                issue.number, Runnability.INELIGIBLE,
                f"the issue does not carry {policy.issueLabel}",
            )
        if issue.has_label(policy.humanLabel):
            return Verdict(
                issue.number, Runnability.NEEDS_HUMAN,
                f"the issue carries {policy.humanLabel}",
            )
        if issue.has_label(policy.failedLabel):
            return Verdict(
                issue.number, Runnability.NEEDS_HUMAN,
                f"the issue carries {policy.failedLabel}",
            )

        ambiguous, notes = ambiguity.get(issue.number, (False, ()))
        if ambiguous:
            return Verdict(
                issue.number, Runnability.AMBIGUOUS,
                notes[0] if notes else "the dependency state cannot be established",
            )

        if issue.number in in_cycle:
            ring = next(c for c in self.cycles if issue.number in c)
            return Verdict(
                issue.number, Runnability.CYCLE,
                "dependency cycle: " + " -> ".join(f"#{n}" for n in ring + [ring[0]]),
                tuple(graph.get(issue.number, ())),
            )

        unmet: List[int] = []
        for blocker in graph.get(issue.number, ()):
            try:
                other = self.resolver.issue(blocker)
            except Exception as exc:
                return Verdict(
                    issue.number, Runnability.AMBIGUOUS,
                    f"blocker #{blocker} could not be read: {exc}",
                    (blocker,),
                )
            if other.is_open:
                unmet.append(blocker)
        if unmet:
            return Verdict(issue.number, Runnability.BLOCKED, "", tuple(sorted(unmet)))

        claim = self.claims.live_claim(issue) if self.claims else None
        if claim is not None:
            return Verdict(
                issue.number, Runnability.CLAIMED,
                f"claimed by run {claim.run_id} at {claim.started_at}",
            )

        return Verdict(issue.number, Runnability.RUNNABLE)

    @staticmethod
    def order(verdicts: Sequence[Verdict]) -> List[int]:
        """The order the scheduler starts runnable issues in.

        Lowest issue number first. The backlog is written in dependency order,
        so the lowest open number is normally the one that unblocks the most,
        and a stable order makes a dry run reproducible.
        """
        return [v.issue for v in verdicts if v.runnability is Runnability.RUNNABLE]
