"""What the operator sees while the queue runs.

An unattended run lasts for hours. The terminal is the only thing a human
looks at, so it must answer four questions at a glance:

    which issue is being worked on
    which stage it is in
    how long that stage has taken
    what happened when something failed

Everything else is evidence, and evidence belongs in a file.

The module has no knowledge of GitHub, git or agentbox. It receives stage
transitions and renders them. That keeps the presentation outside the security
boundary: nothing here decides anything, and nothing here can weaken a gate.

Four levels:

    quiet     failures, human intervention and the final summary
    compact   the stage view, the default
    verbose   the stage view and the coordinator's own notes
    debug     everything, including every raw line the child wrote

One rule governs the terminal handling. A TTY may be repainted in place,
because a human is watching and the previous frame has no value. A file, a
pipe and a CI log may not, because the previous frame is the record. The two
renderings carry the SAME lines; the interactive one merely overwrites the
line it is about to replace.
"""

from __future__ import annotations

import datetime
import enum
import json
import threading
import time
from typing import Callable, List, Optional, Sequence


# ----------------------------------------------------------------- stages --


class Stage(enum.Enum):
    """The conceptual lifecycle of one issue.

    Not every issue passes through every stage. An adopted branch runs no
    implementer, a repository with no Codex credential runs no reviewer, and a
    policy with autoMerge off stops at PR. A stage that did not happen is not
    printed, and a stage that was deliberately not run is printed as skipped
    with the reason. The queue never draws a stage it did not reach.
    """

    PLAN = "PLAN"
    CLAIM = "CLAIM"
    IMPLEMENT = "IMPLEMENT"
    CHECK = "CHECK"
    REVIEW = "REVIEW"
    IMPORT = "IMPORT"
    PUSH = "PUSH"
    PR = "PR"
    CI = "CI"
    MERGE = "MERGE"
    DONE = "DONE"


#: The stages that can take minutes. Only these announce themselves when they
#: start; a stage that finishes in a moment would otherwise print twice.
LONG_STAGES = frozenset(
    {Stage.IMPLEMENT, Stage.CHECK, Stage.REVIEW, Stage.CI, Stage.MERGE}
)


class Status(enum.Enum):
    RUNNING = "running"
    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"
    ATTENTION = "attention"
    SECURITY = "security"

    @property
    def final(self) -> bool:
        return self is not Status.RUNNING


#: A security or integrity failure must not look like a failing test. It gets
#: a marker of its own, and a banner the eye cannot miss.
_MARKS_UNICODE = {
    Status.RUNNING: "●",     # a filled circle
    Status.OK: "✓",          # a check mark
    Status.SKIPPED: "-",
    Status.FAILED: "✗",      # a ballot X
    Status.ATTENTION: "!",
    Status.SECURITY: "⚠",    # a warning sign
}

_MARKS_ASCII = {
    Status.RUNNING: ">",
    Status.OK: "+",
    Status.SKIPPED: "-",
    Status.FAILED: "x",
    Status.ATTENTION: "!",
    Status.SECURITY: "*",
}

_ARROW_UNICODE = "→"
_ARROW_ASCII = "->"
_DOT_UNICODE = "·"
_DOT_ASCII = "-"

LEVELS = ("quiet", "compact", "verbose", "debug")

#: The column the stage detail starts in. It is wide enough for NEEDS_HUMAN.
_NAME_WIDTH = 17


# -------------------------------------------------------------- utilities --


def human_duration(seconds: float) -> str:
    """``24s``, ``7m 18s``, ``1h 02m 03s``.

    Seconds are zero-padded once a larger unit is present, so a column of
    durations stays aligned and a glance compares them correctly.
    """
    total = int(max(0, seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {secs:02d}s"


def bounded_tail(text: str, max_lines: int = 12, max_columns: int = 200) -> List[str]:
    """The last few meaningful lines of some output, each one bounded.

    A failure needs enough to recognise, not enough to reconstruct. The whole
    output is in the run log, and the failure block says where.
    """
    lines = [line.rstrip() for line in (text or "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    tail = lines[-max_lines:] if max_lines > 0 else []
    out = []
    for line in tail:
        if len(line) > max_columns:
            line = line[: max_columns - 1] + "…"
        out.append(line)
    return out


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------ the base UI --


class NullUi:
    """Accepts every call and renders nothing.

    It is the default, so a Coordinator built without a UI still runs. Every
    method below is the whole interface the coordinator may use.
    """

    level = "quiet"
    wants_raw = False
    dot = _DOT_ASCII
    arrow = _ARROW_ASCII
    marks = _MARKS_ASCII

    def run_header(self, version, slug, runnable, parallel, run_id, log_path=""):
        pass

    def wave(self, index, numbers):
        pass

    def issue_start(self, index, total, number, title):
        pass

    def stage(self, stage, status=Status.RUNNING, detail="", key=""):
        pass

    def stage_detail(self, detail, key=""):
        pass

    def note(self, text, level="verbose"):
        pass

    def warn(self, text):
        pass

    def raw(self, line):
        pass

    def failure(self, stage, detail, tail=(), log_path="", retry=""):
        pass

    def issue_end(self, number, status, detail=""):
        pass

    def summary(self, report, policy, extra_lines=()):
        pass

    def tick(self, now=None):
        pass

    def start(self):
        pass

    def close(self):
        pass


# ------------------------------------------------------------ the stage UI --


class StageUi(NullUi):
    """The compact stage renderer, and its verbose and debug settings.

    One class carries all four levels because they differ only in what they
    let through. A separate class per level would let the four drift, and the
    stage model is the thing that must not drift.
    """

    def __init__(
        self,
        stream,
        level: str = "compact",
        tty: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
        heartbeat_seconds: float = 60.0,
        refresh_seconds: float = 1.0,
        unicode: Optional[bool] = None,
        max_tail_lines: int = 12,
        max_tail_columns: int = 200,
        transcript: Optional[Callable[[str], None]] = None,
        multi: bool = False,
    ):
        if level not in LEVELS:
            raise ValueError(f"unknown output level: {level}")
        self.stream = stream
        self.level = level
        self.clock = clock
        self.heartbeat_seconds = heartbeat_seconds
        self.refresh_seconds = refresh_seconds
        self.max_tail_lines = max_tail_lines
        self.max_tail_columns = max_tail_columns
        self.transcript = transcript

        if tty is None:
            tty = bool(getattr(stream, "isatty", lambda: False)())
        # In-place repainting is for a human at a terminal. A redirected
        # stream keeps every line, and never receives a control sequence.
        self.tty = bool(tty)
        # Several issues at a time cannot share one active line. The stage view
        # then becomes purely line-oriented, and every line names its issue, so
        # two workers can interleave without either becoming unreadable. The
        # heartbeat is off in that shape, because there is no single active
        # stage for it to refresh.
        self.multi = bool(multi)
        self.in_place = (
            self.tty and not self.multi and level in ("quiet", "compact")
        )

        if unicode is None:
            unicode = "utf" in (getattr(stream, "encoding", "") or "").lower()
        self.marks = _MARKS_UNICODE if unicode else _MARKS_ASCII
        self.arrow = _ARROW_UNICODE if unicode else _ARROW_ASCII
        self.dot = _DOT_UNICODE if unicode else _DOT_ASCII

        self._lock = threading.RLock()
        self._pending = ""           # a line written without its newline
        self._last_blank = True      # so a leading blank line is dropped
        self._stage: Optional[Stage] = None
        self._stage_started = 0.0
        self._stage_detail = ""
        self._stage_key = ""
        self._painted_at = 0.0
        self._issue_started = 0.0
        self._issue = 0
        self._local = threading.local()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ plumbing --

    @property
    def wants_raw(self) -> bool:
        return self.level == "debug"

    # Every write below takes the renderer lock, and the lock is re-entrant,
    # so a public method may hold it across a whole block and the primitives
    # still take it when they are called on their own. The lock is at the
    # BOTTOM as well as the top on purpose: a write path added later cannot
    # bypass it by forgetting the outer "with".
    #
    # A multi-line block is written under one hold. Two issues at a time means
    # two threads, and a failure block whose evidence had another issue's
    # progress line in the middle of it would be worse than no block at all.

    def _record(self, text: str) -> None:
        if self.transcript is None:
            return
        with self._lock:
            for line in text.split("\n"):
                self.transcript(line)

    def _shows(self, level: str) -> bool:
        return LEVELS.index(self.level) >= LEVELS.index(level)

    def _finish_pending(self) -> None:
        with self._lock:
            if self._pending:
                self.stream.write("\n")
                self._pending = ""

    def _write(self, text: str) -> None:
        """Emit one finished line. It is never overwritten again.

        Two blank lines in a row are collapsed into one. A block that ends
        with a blank line and a block that starts with one both exist for the
        same reason, and the reader only needs the gap once.
        """
        with self._lock:
            self._finish_pending()
            text = text.rstrip()
            if not text:
                if self._last_blank:
                    return
                self._last_blank = True
            else:
                self._last_blank = False
            self.stream.write(text + "\n")
            self.stream.flush()

    def _repaint(self, text: str) -> None:
        """Emit the active line. On a TTY it replaces the previous frame."""
        with self._lock:
            text = text.rstrip()
            if self.in_place:
                self.stream.write("\r\x1b[2K" + text)
                self._pending = text
            else:
                self._finish_pending()
                self.stream.write(text + "\n")
            self.stream.flush()
            self._last_blank = False
            self._painted_at = self.clock()

    # -------------------------------------------------------------- header --

    def run_header(self, version, slug, runnable, parallel, run_id, log_path=""):
        plural = "" if runnable == 1 else "s"
        shape = "sequential" if parallel <= 1 else f"{parallel} at a time"
        head = f"agentq {version}"
        sub = f"{slug} {self.dot} {runnable} runnable issue{plural} {self.dot} {shape}"
        with self._lock:
            self._record(head)
            self._record(sub)
            if self._shows("compact"):
                self._write(head)
                self._write(sub)
            self._record(f"run id {run_id}")
            if log_path:
                self._record(f"run log {log_path}")
            if self._shows("verbose"):
                self._write(f"run id {run_id}")
                if log_path:
                    self._write(f"run log {log_path}")
            if self._shows("compact"):
                self._write("")

    def wave(self, index, numbers):
        text = "wave " + str(index) + ": " + ", ".join(f"#{n}" for n in numbers)
        with self._lock:
            self._record(text)
            if self._shows("verbose"):
                self._write(text)

    # --------------------------------------------------------------- issue --

    def issue_start(self, index, total, number, title):
        # The thread-local fields are this thread's, but the shared ones and
        # the stream are not, so the whole frame is opened under one hold.
        self._local.issue = number
        self._local.started = self.clock()
        title = (title or "").strip()
        text = f"[{index}/{total}] #{number}" + (f" {title}" if title else "")
        with self._lock:
            self._close_stage()
            self._issue = number
            self._issue_started = self._local.started
            self._record(text)
            if self._shows("compact"):
                self._write(text)

    def issue_end(self, number, status, detail=""):
        started = getattr(self._local, "started", self._issue_started)
        elapsed = human_duration(self.clock() - started)
        detail = detail.strip()
        joined = f"{detail} {self.dot} {elapsed}" if detail else elapsed
        with self._lock:
            self._close_stage()
            line = self._stage_line(Stage.DONE, status, joined, issue=number)
            self._record(line)
            if self._shows("compact") or status in (
                Status.FAILED, Status.ATTENTION, Status.SECURITY
            ):
                self._write(line)
            if self._shows("compact"):
                self._write("")
        self._local.issue = 0
        self._issue = 0

    # --------------------------------------------------------------- stage --

    def _stage_line(self, stage, status, detail, issue=0) -> str:
        mark = self.marks[status]
        name = stage.value if isinstance(stage, Stage) else str(stage)
        if self.multi:
            issue = issue or getattr(self._local, "issue", 0)
            tag = f"#{issue} " if issue else ""
            return f"  {mark} {tag}{name:<{_NAME_WIDTH}}{detail}".rstrip()
        return f"  {mark} {name:<{_NAME_WIDTH}}{detail}".rstrip()

    def _elapsed_detail(self) -> str:
        elapsed = human_duration(self.clock() - self._stage_started)
        if self._stage_detail:
            return f"{elapsed} {self.dot} {self._stage_detail}"
        return elapsed

    def _close_stage(self) -> None:
        """End the active line so the next output starts on its own line."""
        with self._lock:
            self._stage = None
            self._finish_pending()
            self.stream.flush()

    def stage(self, stage, status=Status.RUNNING, detail="", key=""):
        with self._lock:
            if self.multi:
                self._local.stage = stage if status is Status.RUNNING else None
                self._local.stage_started = self.clock()
                self._local.stage_detail = detail
                if status is Status.RUNNING and stage not in LONG_STAGES:
                    return
                line = self._stage_line(stage, status, detail)
                self._record(line)
                if self._shows("compact"):
                    self._write(line)
                return
            if status is Status.RUNNING:
                self._stage = stage
                self._stage_started = self.clock()
                self._stage_detail = detail
                self._stage_key = key
                self._painted_at = 0.0
                # A stage that finishes in a moment prints once, when it is
                # done. Announcing it first would double every short line.
                if stage in LONG_STAGES:
                    line = self._stage_line(stage, status, self._elapsed_detail())
                    self._record(line)
                    if self._shows("compact"):
                        self._repaint(line)
                return

            was_active = self._stage is stage
            if was_active and not detail:
                detail = self._stage_detail
            if was_active and stage in LONG_STAGES:
                # A stage that took minutes says how many. The elapsed time is
                # the first thing a reader of a long run looks for.
                elapsed = human_duration(self.clock() - self._stage_started)
                detail = f"{elapsed} {self.dot} {detail}" if detail else elapsed
            line = self._stage_line(stage, status, detail)
            self._record(line)
            self._stage = None
            if self._shows("compact"):
                if was_active:
                    self._repaint(line)
                    self._finish_pending()
                    self.stream.flush()
                else:
                    self._write(line)

    def stage_detail(self, detail, key=""):
        """Replace the detail of the active stage.

        In the several-issues-at-a-time shape there is no single active line,
        so a changed key prints one more line and an unchanged key prints
        nothing.

        ``key`` names the deterministic progress this detail carries, such as
        the iteration number or the CI state. A changed key is a real
        transition and is always shown. An unchanged key is only a fresher
        clock, and it waits for the heartbeat.
        """
        with self._lock:
            if self.multi:
                stage = getattr(self._local, "stage", None)
                if stage is None or key == getattr(self._local, "key", None):
                    return
                self._local.key = key
                elapsed = human_duration(
                    self.clock() - getattr(self._local, "stage_started", self.clock())
                )
                line = self._stage_line(
                    stage, Status.RUNNING,
                    f"{elapsed} {self.dot} {detail}" if detail else elapsed,
                )
                self._record(line)
                if self._shows("compact"):
                    self._write(line)
                return
            if self._stage is None:
                return
            changed = key != self._stage_key
            self._stage_detail = detail
            self._stage_key = key
            line = self._stage_line(self._stage, Status.RUNNING, self._elapsed_detail())
            self._record(line)
            if not self._shows("compact"):
                return
            if self.in_place or changed:
                self._repaint(line)
            elif self.clock() - self._painted_at >= self.heartbeat_seconds:
                self._repaint(line)

    def tick(self, now=None):
        """The heartbeat. A long stage must never look hung.

        On a TTY the active line is repainted, so the clock advances in place.
        On any other stream a new line is appended, at the heartbeat interval,
        so a log stays readable and finite.
        """
        with self._lock:
            if self.multi or self._stage is None or not self._shows("compact"):
                return
            now = self.clock() if now is None else now
            due = self.refresh_seconds if self.in_place else self.heartbeat_seconds
            if now - self._painted_at < due:
                return
            line = self._stage_line(self._stage, Status.RUNNING, self._elapsed_detail())
            if not self.in_place:
                self._record(line)
            self._repaint(line)

    # ---------------------------------------------------------------- text --

    def note(self, text, level="verbose"):
        with self._lock:
            self._record(text)
            if self._shows(level):
                self._write("    " + text)

    def warn(self, text):
        with self._lock:
            self._record("warning: " + text)
            self._write(f"  {self.marks[Status.ATTENTION]} warning: {text}")

    def raw(self, line):
        line = line.rstrip("\n")
        with self._lock:
            self._record(line)
            if self.level == "debug":
                self._write("      " + line)

    # ------------------------------------------------------------- failure --

    def failure(self, stage, detail, tail=(), log_path="", retry=""):
        """A bounded, actionable failure block.

        It is printed at every level, quiet included. A failure that a level
        hides is a failure that reaches nobody.
        """
        with self._lock:
            status = Status.SECURITY if stage == "SECURITY" else Status.FAILED
            lines = [self._stage_line(stage, status, detail)]
            if status is Status.SECURITY:
                lines.append(
                    "    a security or integrity failure, not a failing test"
                )
            tail = list(tail)[: self.max_tail_lines]
            if tail:
                lines.append("")
                lines.append("  Last output:")
                lines.extend("    " + t for t in tail)
            if log_path:
                lines.append(f"    log: {log_path}")
            if retry:
                lines.append("")
                lines.append(f"  {self.arrow} {retry}")
            lines.append("")
            self._stage = None
            for line in lines:
                self._record(line)
                self._write(line)

    # ------------------------------------------------------------- summary --

    def summary(self, report, policy, extra_lines=()):
        with self._lock:
            self._close_stage()
            for line in render_compact_summary(self, report, policy):
                self._record(line)
                self._write(line)
            for line in extra_lines:
                self._record(line)
                if self._shows("verbose"):
                    self._write(line)

    # ----------------------------------------------------------- heartbeat --

    def start(self):
        """Start the heartbeat thread.

        It is a daemon, it only paints, and it holds the same lock as every
        other painter. An interrupt therefore reaches the main thread as it
        always did, and the process still exits when the main thread does.
        """
        if self._thread is not None or self.multi or not self._shows("compact"):
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(self.refresh_seconds if self.in_place else 1.0):
                try:
                    self.tick()
                except Exception:
                    return

        self._thread = threading.Thread(
            target=loop, name="agentqueue-heartbeat", daemon=True
        )
        self._thread.start()

    def close(self):
        # The heartbeat thread takes the same lock, so it is stopped and joined
        # BEFORE the lock is taken here. Joining while holding it would wait
        # for a thread that is waiting for it.
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        with self._lock:
            self._finish_pending()
            try:
                self.stream.flush()
            except ValueError:
                pass


# --------------------------------------------------------- the JSON stream --


class JsonUi(NullUi):
    """One JSON object per line, for a machine.

    The same events the terminal renderer receives. Nothing is summarised
    away, and no control sequence is ever written.
    """

    level = "compact"
    wants_raw = False

    def __init__(self, stream, transcript: Optional[Callable[[str], None]] = None):
        self.stream = stream
        self.transcript = transcript
        self._lock = threading.RLock()
        # Which issue and which stage this THREAD is reporting on. Several
        # issues at a time means several threads write to the same stream, and
        # an event carrying another thread's issue number would be worse than
        # an event carrying none: it would be a wrong answer, not a missing one.
        self._local = threading.local()

    @property
    def _issue(self) -> int:
        return getattr(self._local, "issue", 0)

    @_issue.setter
    def _issue(self, number: int) -> None:
        self._local.issue = number

    @property
    def _stage(self) -> str:
        return getattr(self._local, "stage", "")

    @_stage.setter
    def _stage(self, name: str) -> None:
        self._local.stage = name

    def _emit(self, event: str, **fields) -> None:
        record = {"time": _iso_now(), "event": event}
        if self._issue:
            record["issue"] = self._issue
        record.update({k: v for k, v in fields.items() if v not in ("", None)})
        line = json.dumps(record, sort_keys=True)
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()
            if self.transcript is not None:
                self.transcript(line)

    def run_header(self, version, slug, runnable, parallel, run_id, log_path=""):
        self._emit("run.start", version=version, repository=slug,
                   runnable=runnable, maxParallel=parallel, runId=run_id,
                   logPath=log_path)

    def wave(self, index, numbers):
        self._emit("wave", wave=index, issues=list(numbers))

    def issue_start(self, index, total, number, title):
        self._issue = number
        self._emit("issue.start", position=index, total=total, title=title)

    def stage(self, stage, status=Status.RUNNING, detail="", key=""):
        name = stage.value if isinstance(stage, Stage) else str(stage)
        self._stage = name
        self._emit("stage", stage=name, status=status.value, detail=detail,
                   progress=key)

    def stage_detail(self, detail, key=""):
        self._emit("stage.progress", stage=self._stage, detail=detail, progress=key)

    def note(self, text, level="verbose"):
        self._emit("note", text=text, level=level)

    def warn(self, text):
        self._emit("warning", text=text)

    def failure(self, stage, detail, tail=(), log_path="", retry=""):
        name = stage.value if isinstance(stage, Stage) else str(stage)
        self._emit("failure", stage=name, detail=detail, tail=list(tail),
                   logPath=log_path, retry=retry)

    def issue_end(self, number, status, detail=""):
        self._emit("issue.end", status=status.value, detail=detail)
        self._issue = 0

    def summary(self, report, policy, extra_lines=()):
        from .model import Outcome, Runnability

        self._emit(
            "run.end",
            completed=report.count(Outcome.SUCCESS),
            merged=report.merged,
            failed=report.count(Outcome.FAILED_FINAL)
            + report.count(Outcome.FAILED_TRANSIENT),
            needsHuman=report.count(Outcome.NEEDS_HUMAN),
            overBudget=report.count(Outcome.BUDGET_EXCEEDED),
            remaining=sum(
                1 for v in report.verdicts if v.runnability is Runnability.RUNNABLE
            ),
            elapsedSeconds=report.elapsed_seconds,
            stoppedForSecurity=report.stopped_for_security,
            issues=[
                {
                    "issue": r.issue,
                    "outcome": r.outcome.value,
                    "pullRequest": r.pull_request,
                    "merged": r.merged,
                    "detail": r.detail,
                }
                for r in report.results
            ],
        )


# ------------------------------------------------------- the final summary --


def render_compact_summary(ui, report, policy) -> List[str]:
    """The closing block: one line per issue, then the counts.

    It is derived from the same report the verbose summary reads, so the two
    can disagree about detail but never about the outcome.
    """
    from .model import Outcome, Runnability

    marks = getattr(ui, "marks", _MARKS_ASCII)
    dot = getattr(ui, "dot", _DOT_ASCII)
    arrow = getattr(ui, "arrow", _ARROW_ASCII)

    stopped = bool(report.stopped_for_security)
    lines = ["", "agentq stopped" if stopped else "agentq complete", ""]

    status_of = {
        Outcome.SUCCESS: Status.OK,
        Outcome.BLOCKED: Status.SKIPPED,
        Outcome.NEEDS_HUMAN: Status.ATTENTION,
        Outcome.BUDGET_EXCEEDED: Status.ATTENTION,
        Outcome.FAILED_FINAL: Status.FAILED,
        Outcome.FAILED_TRANSIENT: Status.FAILED,
        Outcome.SECURITY_OR_INTEGRITY_FAILURE: Status.SECURITY,
    }
    for result in report.results:
        mark = marks[status_of.get(result.outcome, Status.FAILED)]
        if result.merged:
            tail = f"{arrow} PR #{result.pull_request} merged"
        elif result.pull_request:
            tail = f"{arrow} PR #{result.pull_request} {result.detail}"
        else:
            tail = result.detail or result.outcome.value
        lines.append(f"  {mark} #{result.issue} {tail}".rstrip())
    if not report.results:
        lines.append("  nothing was runnable")
    lines.append("")

    failed = report.count(Outcome.FAILED_FINAL) + report.count(Outcome.FAILED_TRANSIENT)
    counts = [
        f"{report.count(Outcome.SUCCESS)} completed",
        f"{failed} failed",
        f"{report.count(Outcome.NEEDS_HUMAN)} human intervention",
    ]
    # Only when it happened. A budget breach is rare, and a permanent
    # "0 over budget" would teach a reader to stop looking at the line.
    over_budget = report.count(Outcome.BUDGET_EXCEEDED)
    if over_budget:
        counts.append(f"{over_budget} over budget")
    counts.append(human_duration(report.elapsed_seconds))
    lines.append(f" {dot} ".join(counts))

    remaining = [
        v for v in report.verdicts if v.runnability is Runnability.RUNNABLE
    ]
    blocked = [v for v in report.verdicts if v.runnability is Runnability.BLOCKED]
    if remaining:
        lines.append(f"{len(remaining)} issue(s) still carry {policy.issueLabel}")
    if blocked:
        lines.append(f"{len(blocked)} issue(s) are still blocked by a dependency")
    if stopped:
        lines.append("")
        lines.append(
            f"  {marks[Status.SECURITY]} THE QUEUE STOPPED: "
            + report.stopped_for_security
        )
        lines.append(
            "  This is a security or integrity failure, not a failing test. "
            "Read the run log before starting another run."
        )
    return lines
