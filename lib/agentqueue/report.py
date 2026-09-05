"""What the operator sees.

Two outputs. The dry run prints the plan. The run prints the summary. Both
read the same verdict list, so a plan cannot disagree with a run.
"""

from __future__ import annotations

from typing import List, Sequence

from .model import Outcome, Runnability, Verdict


def render_plan(verdicts: Sequence[Verdict], cycles: Sequence[Sequence[int]]) -> List[str]:
    lines: List[str] = []
    for verdict in verdicts:
        lines.append("  " + verdict.render())
    order = [v.issue for v in verdicts if v.runnability is Runnability.RUNNABLE]
    lines.append("")
    if order:
        lines.append("  order: " + " -> ".join(f"#{n}" for n in order))
    else:
        lines.append("  order: nothing is runnable")
    if cycles:
        lines.append("")
        for cycle in cycles:
            ring = list(cycle) + [cycle[0]]
            lines.append("  cycle: " + " -> ".join(f"#{n}" for n in ring))
    return lines


def render_summary(report, policy) -> List[str]:
    remaining = [
        v.issue for v in report.verdicts if v.runnability is Runnability.RUNNABLE
    ]
    blocked = [v for v in report.verdicts if v.runnability is Runnability.BLOCKED]
    ambiguous = [v for v in report.verdicts if v.runnability is Runnability.AMBIGUOUS]
    cyclic = [v for v in report.verdicts if v.runnability is Runnability.CYCLE]
    human = [v for v in report.verdicts if v.runnability is Runnability.NEEDS_HUMAN]

    lines = [
        "",
        "== agentqueue summary ==",
        f"  issues completed          {report.count(Outcome.SUCCESS)}",
        f"  pull requests merged      {report.merged}",
        f"  issues blocked            {len(blocked)}",
        f"  issues needing a human    {report.count(Outcome.NEEDS_HUMAN) + len(human)}",
        f"  issues failed             "
        f"{report.count(Outcome.FAILED_FINAL) + report.count(Outcome.FAILED_TRANSIENT)}",
        f"  dependency state unclear  {len(ambiguous)}",
        f"  dependency cycles         {len(cyclic)}",
        f"  remaining {policy.issueLabel:<15} {len(remaining)}",
        f"  agentbox runs             {report.agentbox_runs}",
        f"  check retries             {report.ci_retries}",
        f"  waves                     {report.waves}",
        f"  elapsed                   {report.elapsed_seconds}s",
    ]
    if report.reclaimed:
        lines.append("")
        lines.append("  stale claims recovered:")
        lines.extend(f"    {item}" for item in report.reclaimed)
    if report.results:
        lines.append("")
        lines.append("  per issue:")
        for result in report.results:
            suffix = f" (PR #{result.pull_request})" if result.pull_request else ""
            lines.append(
                f"    #{result.issue} {result.outcome.value}{suffix}"
                f"  {result.detail}"
            )
    if blocked:
        lines.append("")
        lines.append("  still blocked:")
        lines.extend("    " + v.render() for v in blocked)
    if report.stopped_for_security:
        lines.append("")
        lines.append("  THE QUEUE STOPPED: " + report.stopped_for_security)
    return lines
