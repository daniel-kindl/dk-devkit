#!/usr/bin/env python3
"""Deterministic tests for what agentqueue prints.

No network, no container, no model and no real clock. The agent is a scripted
event stream, the terminal is a string buffer, and time is a counter. Every
case below therefore gives the same answer on every machine.

    python3 verify/probes/agentqueue-output.test.py

verify/85-agentqueue.sh runs this file, and it fails the module on any error.

What is proved here:

    the compact stage view is the default, and it holds no raw child output
    the issue counter, the stage order and the deterministic progress numbers
    a skipped review says it was skipped, and says why
    a failure is bounded, names its log, and states the retry
    NEEDS_HUMAN and a security stop are visibly different from each other
    quiet, verbose, debug and JSON each let through exactly what they promise
    a redirected stream never receives a terminal control sequence
    the child's exit code, its summary and its evidence survive the new layer
    an interrupt reaches the caller, and the evidence it produced is on disk
    two issues at a time never report each other's progress
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import agentqueue_fakes as fakes  # noqa: E402
from agentqueue import ui as ui_mod  # noqa: E402
from agentqueue.coordinator import Coordinator  # noqa: E402
from agentqueue.model import (  # noqa: E402
    AGENTBOX_EVENT_PREFIX,
    CheckRun,
    Outcome,
    parse_agentbox_event,
)
from agentqueue.runner import AgentboxRunner  # noqa: E402
from agentqueue.ui import Stage, StageUi, Status, bounded_tail, human_duration  # noqa: E402

READY = "ready-for-agent"

#: One complete, green agentbox run, as the events agentbox publishes.
GREEN_EVENTS = [
    {"event": "sandbox.ready", "branch": "agent/issue-86"},
    {"event": "isolation.ok", "probes": 7, "failed": 0},
    {"event": "implement.start", "agent": "claude", "model": "opus",
     "maxIterations": 4},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 4, "tools": 3},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 2, "maxIterations": 4, "tools": 9},
    {"event": "implement.done", "commits": 1, "iterations": 2},
    {"event": "check.start", "command": "pnpm check", "index": 1, "total": 1},
    {"event": "check.done", "command": "pnpm check", "exitCode": 0},
    {"event": "checks.done", "total": 1, "failed": 0},
    {"event": "review.skipped", "reason": "no Codex credential"},
    {"event": "integrity.ok"},
    {"event": "import.done", "commits": 1, "tip": "deadbeefcafe"},
]


class StepClock:
    """A clock that advances by a fixed step on every reading.

    Elapsed times in the output are then exact, so a test asserts a duration
    instead of tolerating one.
    """

    def __init__(self, step: float = 7.0):
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class Harness:
    """One scripted drain, rendered into a string."""

    def __init__(self, level="compact", tty=False, script=None, issues=None,
                 policy=None, unicode=True, multi=False, clock=None):
        self.stream = io.StringIO()
        self.transcript = []
        self.ui = StageUi(
            self.stream, level=level, tty=tty, clock=clock or StepClock(),
            unicode=unicode, multi=multi,
            transcript=self.transcript.append,
        )
        self.github = fakes.FakeGitHub()
        for number, title in (issues or [(86, "Implement entry-selection module")]):
            self.github.add_issue(number, title, labels=(READY,))
        self.git = fakes.FakeGit()
        self.policy = policy or fakes.make_policy(
            autoMerge=True, mergeWithoutReview=True, checks=["pnpm check"],
        )
        self.runner = fakes.FakeRunner(self.git, script)
        self.github.head_sha_source = lambda b: self.git.refs.get(
            "refs/heads/" + b, "sha-" + b
        )
        self.github.check_runs = lambda sha: [
            CheckRun("Quality", "completed", "success")
        ]
        self._tmp = tempfile.mkdtemp()

    def drain(self):
        coordinator = Coordinator(
            self.github, self.git, self.policy, self.runner, self._tmp,
            os.path.join(_ROOT, "bin", "scan-secrets"),
            emit=lambda line: self.ui.note(line), dry_run=False,
            run_id="testrun", run_log="/state/runs/testrun/queue.log",
            agent_identities=(fakes.AGENT_IDENTITY,),
            sleep=lambda _s: None, ui=self.ui,
        )
        report = coordinator.drain()
        from agentqueue import report as report_mod

        self.ui.summary(
            report, self.policy,
            extra_lines=report_mod.render_summary(report, self.policy),
        )
        self.ui.close()
        return report

    @property
    def text(self) -> str:
        return self.stream.getvalue()

    @property
    def lines(self):
        return self.text.splitlines()

    def stage_lines(self):
        return [
            line.strip() for line in self.lines
            if line.startswith("  ") and not line.startswith("    ")
        ]


def green(**overrides):
    step = {"events": GREEN_EVENTS, "sha": "sha-86"}
    step.update(overrides)
    return step


# ------------------------------------------------------------- the pieces --


class TestDuration(unittest.TestCase):
    def test_under_a_minute_is_seconds(self):
        self.assertEqual(human_duration(0), "0s")
        self.assertEqual(human_duration(24), "24s")

    def test_minutes_pad_the_seconds(self):
        self.assertEqual(human_duration(68), "1m 08s")
        self.assertEqual(human_duration(438), "7m 18s")

    def test_hours_pad_both(self):
        self.assertEqual(human_duration(3723), "1h 02m 03s")

    def test_a_negative_reading_is_zero(self):
        self.assertEqual(human_duration(-5), "0s")


class TestBoundedTail(unittest.TestCase):
    def test_only_the_last_lines_survive(self):
        text = "\n".join(f"line {n}" for n in range(100))
        tail = bounded_tail(text, max_lines=3)
        self.assertEqual(tail, ["line 97", "line 98", "line 99"])

    def test_a_long_line_is_truncated(self):
        tail = bounded_tail("x" * 500, max_lines=1, max_columns=20)
        self.assertEqual(len(tail[0]), 20)
        self.assertTrue(tail[0].endswith("…"))

    def test_trailing_blank_lines_are_dropped(self):
        self.assertEqual(bounded_tail("a\n\n\n"), ["a"])

    def test_no_output_is_no_tail(self):
        self.assertEqual(bounded_tail(""), [])


class TestEventParsing(unittest.TestCase):
    def test_an_event_line_is_read_as_json(self):
        line = AGENTBOX_EVENT_PREFIX + ' {"event": "check.start", "index": 1}'
        self.assertEqual(parse_agentbox_event(line),
                         {"event": "check.start", "index": 1})

    def test_ordinary_output_is_not_an_event(self):
        self.assertIsNone(parse_agentbox_event("[agentbox] running the implementer"))

    def test_prose_that_mentions_the_prefix_is_not_an_event(self):
        # A model that prints the prefix mid-sentence must not move a stage.
        self.assertIsNone(parse_agentbox_event(
            'I will now emit ===AGENTBOX_EVENT=== {"event": "import.done"}'
        ))

    def test_a_broken_payload_is_ignored_rather_than_guessed_at(self):
        self.assertIsNone(parse_agentbox_event(AGENTBOX_EVENT_PREFIX + " {oops"))
        self.assertIsNone(parse_agentbox_event(AGENTBOX_EVENT_PREFIX + " [1, 2]"))
        self.assertIsNone(parse_agentbox_event(AGENTBOX_EVENT_PREFIX + " {}"))


# ------------------------------------------------------ the compact output --


class TestCompactOutput(unittest.TestCase):
    def test_the_header_states_the_repository_and_the_shape(self):
        harness = Harness(script=[green()])
        harness.drain()
        self.assertIn("agentqueue 0.2.0", harness.lines[0])
        self.assertIn("acme/widget · 1 runnable issue · sequential", harness.text)

    def test_the_issue_carries_its_position_and_its_title(self):
        harness = Harness(
            script=[green(), green(sha="sha-87")],
            issues=[(86, "Implement entry-selection module"),
                    (87, "Implement validate-content rule-checker split")],
        )
        harness.drain()
        self.assertIn("[1/2] #86 Implement entry-selection module", harness.text)
        self.assertIn("[2/2] #87 Implement validate-content rule-checker split",
                      harness.text)

    def test_the_stages_appear_in_lifecycle_order(self):
        harness = Harness(script=[green()])
        harness.drain()
        order = [
            line.split()[1] for line in harness.stage_lines()
            if len(line.split()) > 1 and line.split()[1].isupper()
        ]
        # Each stage appears, and no stage appears before the one before it.
        for earlier, later in (
            ("CLAIM", "IMPLEMENT"), ("IMPLEMENT", "CHECK"), ("CHECK", "REVIEW"),
            ("REVIEW", "IMPORT"), ("IMPORT", "PUSH"), ("PUSH", "PR"),
            ("PR", "CI"), ("CI", "MERGE"), ("MERGE", "DONE"),
        ):
            self.assertIn(earlier, order, order)
            self.assertIn(later, order, order)
            self.assertLess(order.index(earlier), order.index(later), order)

    def test_a_skipped_review_says_so_and_says_why(self):
        harness = Harness(script=[green()])
        harness.drain()
        self.assertIn("- REVIEW", harness.text)
        self.assertIn("skipped · no Codex credential", harness.text)
        # It must never read as a review that ran.
        self.assertNotIn("✓ REVIEW", harness.text)

    def test_a_passing_local_check_is_reported_with_its_duration(self):
        harness = Harness(script=[green()])
        harness.drain()
        check = [l for l in harness.stage_lines() if l.startswith("✓ CHECK")]
        self.assertEqual(len(check), 1)
        self.assertIn("1 check passed", check[0])
        self.assertRegex(check[0], r"\d+s")

    def test_agent_progress_is_the_real_iteration_not_a_percentage(self):
        harness = Harness(script=[green()])
        harness.drain()
        self.assertIn("iteration 1/4", harness.text)
        self.assertIn("iteration 2/4", harness.text)
        self.assertNotIn("%", harness.text)

    def test_ci_moves_from_pending_to_passed(self):
        harness = Harness(script=[green()])
        states = ["pending", "pending", "passed"]

        def check_runs(sha):
            state = states.pop(0) if len(states) > 1 else states[0]
            if state == "pending":
                return [CheckRun("Quality", "in_progress")]
            return [CheckRun("Quality", "completed", "success")]

        harness.github.check_runs = check_runs
        harness.drain()
        self.assertIn("● CI", harness.text)
        self.assertIn("pending: Quality", harness.text)
        self.assertIn("✓ CI", harness.text)
        self.assertIn("1 check passed", harness.text)

    def test_the_final_summary_names_every_issue_and_counts_them(self):
        harness = Harness(
            script=[green(), green(sha="sha-87")],
            issues=[(86, "One"), (87, "Two")],
        )
        harness.drain()
        self.assertIn("agentqueue complete", harness.text)
        self.assertRegex(harness.text, r"✓ #86 → PR #\d+ merged")
        self.assertRegex(harness.text, r"✓ #87 → PR #\d+ merged")
        self.assertIn("2 completed · 0 failed · 0 human intervention", harness.text)

    def test_no_raw_child_output_reaches_a_compact_terminal(self):
        noise = [f"thinking about line {n}" for n in range(300)]
        harness = Harness(script=[green(raw=noise)])
        harness.drain()
        self.assertNotIn("thinking about line", harness.text)
        # It is not lost: the transcript holds every one of them.
        self.assertIn("thinking about line 299", "\n".join(harness.transcript))

    def test_a_compact_run_stays_short(self):
        noise = [f"tool call {n}" for n in range(500)]
        harness = Harness(script=[green(raw=noise)])
        harness.drain()
        self.assertLess(len(harness.lines), 40, harness.text)


# ------------------------------------------------------------- the failures --


class TestFailureOutput(unittest.TestCase):
    def _failing_check_script(self):
        failing = {
            "checksPassed": False,
            "failedChecks": [{
                "command": "pnpm check",
                "exitCode": 1,
                "tail": "src/lib/entries.test.ts:42\nExpected 3 entries, received 2",
            }],
            "fixRounds": 0,
            "review": {"skipped": True, "reason": "no Codex credential"},
            "resultCommit": "sha-86",
        }
        return [
            {"summary": failing, "events": GREEN_EVENTS},
            {"summary": failing, "events": GREEN_EVENTS},
            {"summary": failing, "events": GREEN_EVENTS},
        ]

    def test_a_failing_check_shows_the_command_the_evidence_and_the_retry(self):
        harness = Harness(script=self._failing_check_script())
        harness.policy.maxRetries = 2
        harness.drain()
        self.assertIn("✗ CHECK", harness.text)
        self.assertIn("pnpm check", harness.text)
        self.assertIn("Last output:", harness.text)
        self.assertIn("Expected 3 entries, received 2", harness.text)
        self.assertIn("→ retry 1/2", harness.text)
        self.assertIn("→ retry 2/2", harness.text)

    def test_a_failure_names_the_log_that_holds_the_whole_output(self):
        harness = Harness(script=self._failing_check_script())
        harness.drain()
        self.assertIn("log: ", harness.text)
        self.assertIn("implement.log", harness.text)

    def test_the_failure_tail_is_bounded(self):
        long_tail = "\n".join(f"failure line {n}" for n in range(400))
        summary = {
            "checksPassed": False,
            "failedChecks": [{"command": "pnpm check", "exitCode": 1,
                              "tail": long_tail}],
            "fixRounds": 0,
            "review": {"skipped": True, "reason": "none"},
            "resultCommit": "sha-86",
        }
        harness = Harness(script=[{"summary": summary}] * 3)
        harness.drain()
        blocks = harness.text.count("Last output:")
        shown = [l for l in harness.lines if "failure line" in l]
        self.assertGreaterEqual(blocks, 1)
        self.assertLessEqual(len(shown), 12 * blocks)
        self.assertIn("failure line 399", harness.text)
        self.assertNotIn("failure line 0\n", harness.text)

    def test_an_exhausted_retry_budget_asks_for_a_human(self):
        harness = Harness(script=self._failing_check_script())
        report = harness.drain()
        self.assertIn("! NEEDS_HUMAN", harness.text)
        self.assertIs(report.results[0].outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("1 human intervention", harness.text)

    def test_an_agentbox_failure_states_the_exit_code(self):
        harness = Harness(script=[{"exit": 8, "output": "the agent gave up"}])
        report = harness.drain()
        self.assertIn("✗ IMPLEMENT", harness.text)
        self.assertIn("agentbox exited 8", harness.text)
        self.assertIs(report.results[0].outcome, Outcome.FAILED_TRANSIENT)

    def test_a_security_failure_is_not_dressed_as_a_failing_test(self):
        harness = Harness(script=[{
            "exit": 9,
            "output": "DISPOSABLE CLONE INTEGRITY FAILED: 2 change(s)",
        }])
        report = harness.drain()
        self.assertTrue(report.stopped_for_security)
        self.assertIn("⚠ SECURITY", harness.text)
        self.assertIn("a security or integrity failure, not a failing test",
                      harness.text)
        self.assertIn("THE QUEUE STOPPED", harness.text)
        self.assertIn("agentqueue stopped", harness.text)
        # An ordinary failure marker must not be the only thing a reader sees.
        self.assertNotIn("agentqueue complete", harness.text)

    def test_a_credential_in_the_diff_stops_the_queue_visibly(self):
        harness = Harness(script=[green()])
        harness.git.diffs["agent/issue-86-implement-entry-selection-module"] = (
            "+const key = 'AKIA" + "0123456789ABCDEF';\n"
        )
        report = harness.drain()
        self.assertTrue(report.stopped_for_security)
        self.assertIn("⚠ SECURITY", harness.text)
        self.assertIn("nothing was pushed", harness.text)
        self.assertEqual(harness.git.pushed, [])


# ---------------------------------------------------------------- the levels --


class TestOutputLevels(unittest.TestCase):
    def _script(self):
        return [green(raw=["a model sentence", "another model sentence"])]

    def test_quiet_shows_the_summary_and_nothing_else(self):
        harness = Harness(level="quiet", script=self._script())
        harness.drain()
        self.assertNotIn("✓ CLAIM", harness.text)
        self.assertNotIn("● IMPLEMENT", harness.text)
        self.assertNotIn("a model sentence", harness.text)
        self.assertNotIn("== agentqueue summary ==", harness.text)
        self.assertIn("agentqueue complete", harness.text)
        self.assertIn("1 completed", harness.text)

    def test_quiet_still_shows_a_failure(self):
        harness = Harness(level="quiet",
                          script=[{"exit": 8, "output": "the agent gave up"}])
        harness.drain()
        self.assertIn("✗ IMPLEMENT", harness.text)
        self.assertIn("agentbox exited 8", harness.text)

    def test_quiet_still_shows_a_security_stop(self):
        harness = Harness(level="quiet", script=[{
            "exit": 9, "output": "DISPOSABLE CLONE INTEGRITY FAILED: 1 change",
        }])
        harness.drain()
        self.assertIn("⚠ SECURITY", harness.text)
        self.assertIn("THE QUEUE STOPPED", harness.text)

    def test_verbose_adds_the_coordinator_notes_and_keeps_the_stages(self):
        harness = Harness(level="verbose", script=self._script())
        harness.drain()
        self.assertIn("✓ CLAIM", harness.text)
        self.assertIn("wave 1: #86", harness.text)
        self.assertIn("pull request #501", harness.text)
        self.assertIn("== agentqueue summary ==", harness.text)
        # Verbose is not debug: the model's own sentences stay out.
        self.assertNotIn("a model sentence", harness.text)

    def test_debug_adds_every_raw_line(self):
        harness = Harness(level="debug", script=self._script())
        harness.drain()
        self.assertIn("a model sentence", harness.text)
        self.assertIn("another model sentence", harness.text)
        self.assertIn("✓ CLAIM", harness.text)

    def test_an_unknown_level_is_refused(self):
        with self.assertRaises(ValueError):
            StageUi(io.StringIO(), level="loud")

    def test_the_command_line_allows_one_output_mode_at_a_time(self):
        from agentqueue.cli import build_parser

        parser = build_parser()
        for first, second in (
            ("--quiet", "--verbose"), ("--quiet", "--debug"),
            ("--verbose", "--debug"), ("--json", "--verbose"),
            ("--json", "--quiet"), ("--json", "--debug"),
        ):
            with self.assertRaises(SystemExit, msg=f"{first} {second}"):
                with open(os.devnull, "w", encoding="utf-8") as quiet:
                    stderr, sys.stderr = sys.stderr, quiet
                    try:
                        parser.parse_args(
                            ["drain", "--repo", ".", first, second]
                        )
                    finally:
                        sys.stderr = stderr

    def test_each_output_mode_is_accepted_on_its_own(self):
        from agentqueue.cli import build_parser

        parser = build_parser()
        for flag in ("--quiet", "--verbose", "--debug", "--json"):
            args = parser.parse_args(["drain", "--repo", ".", flag])
            self.assertTrue(
                args.quiet or args.verbose or args.debug or args.json_out
            )


class TestJsonOutput(unittest.TestCase):
    def test_every_event_is_one_json_object(self):
        stream = io.StringIO()
        ui = ui_mod.JsonUi(stream)
        harness = Harness(script=[green()])
        harness.ui = ui
        report = harness.drain()
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        kinds = [r["event"] for r in records]
        self.assertIn("run.start", kinds)
        self.assertIn("issue.start", kinds)
        self.assertIn("stage", kinds)
        self.assertIn("run.end", kinds)
        end = [r for r in records if r["event"] == "run.end"][0]
        self.assertEqual(end["completed"], 1)
        self.assertEqual(end["merged"], 1)
        self.assertEqual(report.count(Outcome.SUCCESS), 1)

    def test_no_control_sequence_ever_reaches_the_json_stream(self):
        stream = io.StringIO()
        harness = Harness(script=[green()])
        harness.ui = ui_mod.JsonUi(stream)
        harness.drain()
        self.assertNotIn("\x1b", stream.getvalue())
        self.assertNotIn("\r", stream.getvalue())


# ------------------------------------------------------------- the terminal --


class TestTerminalBehaviour(unittest.TestCase):
    def test_a_redirected_stream_receives_no_control_sequence(self):
        harness = Harness(tty=False, script=[green()])
        harness.drain()
        self.assertNotIn("\x1b", harness.text)
        self.assertNotIn("\r", harness.text)

    def test_a_redirected_stream_keeps_one_line_per_transition(self):
        harness = Harness(tty=False, script=[green()])
        harness.drain()
        for line in harness.lines:
            self.assertEqual(line, line.rstrip())
        self.assertGreater(len([l for l in harness.lines if l.startswith("  ")]), 5)

    def test_an_interactive_terminal_repaints_the_active_line(self):
        harness = Harness(tty=True, script=[green()])
        harness.drain()
        self.assertIn("\r\x1b[2K", harness.text)

    def test_an_interactive_terminal_and_a_file_carry_the_same_lines(self):
        def rendered(tty):
            harness = Harness(tty=tty, script=[green()], clock=StepClock())
            harness.drain()
            text = harness.text.replace("\r\x1b[2K", "\n")
            return [
                l.strip() for l in text.splitlines()
                if l.strip().startswith(("✓", "-", "●", "!", "⚠"))
            ]
        # An interactive run overwrites frames, so it holds at least what a
        # redirected run holds. Every finished stage must appear in both.
        interactive = rendered(True)
        redirected = rendered(False)
        finished = [l for l in redirected if l.startswith(("✓", "-", "!"))]
        for line in finished:
            self.assertIn(line, interactive)

    def test_ascii_markers_are_available_for_a_terminal_that_needs_them(self):
        harness = Harness(script=[green()], unicode=False)
        harness.drain()
        self.assertNotIn("✓", harness.text)
        self.assertIn("+ CLAIM", harness.text)
        self.assertIn("- REVIEW", harness.text)

    def test_the_stream_encoding_decides_when_nothing_is_stated(self):
        class Utf8(io.StringIO):
            encoding = "UTF-8"

        class Ascii(io.StringIO):
            encoding = "ascii"

        self.assertEqual(StageUi(Utf8()).marks[Status.OK], "✓")
        self.assertEqual(StageUi(Ascii()).marks[Status.OK], "+")


class TestHeartbeat(unittest.TestCase):
    def _running_ui(self, tty):
        clock = StepClock(step=0.0)
        stream = io.StringIO()
        ui = StageUi(stream, level="compact", tty=tty, clock=clock,
                     unicode=True, heartbeat_seconds=60.0, refresh_seconds=1.0)
        ui.issue_start(1, 1, 86, "Long one")
        ui.stage(Stage.IMPLEMENT, Status.RUNNING, "Claude")
        return ui, stream, clock

    def test_a_redirected_stream_gets_one_new_line_per_interval(self):
        ui, stream, clock = self._running_ui(tty=False)
        before = len(stream.getvalue().splitlines())
        clock.now = 30.0
        ui.tick()
        self.assertEqual(len(stream.getvalue().splitlines()), before)
        clock.now = 61.0
        ui.tick()
        self.assertEqual(len(stream.getvalue().splitlines()), before + 1)
        clock.now = 121.0
        ui.tick()
        self.assertEqual(len(stream.getvalue().splitlines()), before + 2)
        self.assertIn("1m 01s", stream.getvalue())
        self.assertIn("2m 01s", stream.getvalue())

    def test_an_interactive_terminal_refreshes_in_place(self):
        ui, stream, clock = self._running_ui(tty=True)
        clock.now = 5.0
        ui.tick()
        clock.now = 10.0
        ui.tick()
        painted = stream.getvalue().count("\r\x1b[2K")
        self.assertGreaterEqual(painted, 3)
        self.assertEqual(stream.getvalue().count("\n"), 1)  # the issue header

    def test_a_finished_stage_has_no_heartbeat(self):
        ui, stream, clock = self._running_ui(tty=False)
        ui.stage(Stage.IMPLEMENT, Status.OK, "1 commit")
        before = stream.getvalue()
        clock.now = 600.0
        ui.tick()
        self.assertEqual(stream.getvalue(), before)

    def test_a_meaningful_transition_does_not_wait_for_the_heartbeat(self):
        ui, stream, clock = self._running_ui(tty=False)
        before = len(stream.getvalue().splitlines())
        clock.now = 3.0
        ui.stage_detail("Claude · iteration 2/4", key="implement:2")
        self.assertEqual(len(stream.getvalue().splitlines()), before + 1)
        # The same progress again is only a fresher clock, and it waits.
        clock.now = 6.0
        ui.stage_detail("Claude · iteration 2/4", key="implement:2")
        self.assertEqual(len(stream.getvalue().splitlines()), before + 1)


class TestSeveralIssuesAtATime(unittest.TestCase):
    def test_every_line_names_its_issue(self):
        harness = Harness(
            script=[green(), green(sha="sha-87")],
            issues=[(86, "One"), (87, "Two")],
            policy=fakes.make_policy(autoMerge=True, mergeWithoutReview=True,
                                     checks=["pnpm check"], maxParallel=2),
            multi=True,
        )
        harness.drain()
        stages = [l for l in harness.lines if l.startswith("  ✓")]
        self.assertTrue(stages)
        for line in stages:
            self.assertRegex(line, r"^  ✓ #\d+ ")

    def test_no_control_sequence_is_written_when_several_issues_run(self):
        harness = Harness(
            tty=True, multi=True, script=[green()],
            policy=fakes.make_policy(autoMerge=True, mergeWithoutReview=True,
                                     checks=["pnpm check"], maxParallel=2),
        )
        harness.drain()
        self.assertNotIn("\x1b", harness.text)


class TestConcurrentAttribution(unittest.TestCase):
    """Two issues at a time must never report each other's progress.

    Every case below forces a REAL overlap with a barrier, so state that is
    per process rather than per issue is guaranteed to be read by the wrong
    thread. A test that only ran two issues one after the other would pass
    with the state shared, which is exactly the defect these look for.
    """

    def _threads(self, worker, count=2, timeout=10):
        barrier = threading.Barrier(count, timeout=timeout)
        errors = []

        def guarded(number):
            try:
                worker(number, barrier)
            except BaseException as exc:  # a barrier timeout must be visible
                errors.append(exc)

        threads = [
            threading.Thread(target=guarded, args=(n,))
            for n in (86, 87)[:count]
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=timeout)
            self.assertFalse(thread.is_alive(), "a worker did not finish")
        self.assertEqual(errors, [])

    def test_json_attributes_every_stage_to_the_issue_that_reached_it(self):
        stream = io.StringIO()
        ui = ui_mod.JsonUi(stream)

        def worker(number, barrier):
            ui.issue_start(1, 2, number, f"issue {number}")
            # Both issues have started before either reports a stage. A
            # shared "current issue" is now the other thread's.
            barrier.wait()
            ui.stage(Stage.CLAIM, Status.OK, f"agent/issue-{number}")
            barrier.wait()
            ui.stage(Stage.PUSH, Status.OK, f"agent/issue-{number}")
            ui.issue_end(number, Status.OK, "done")

        self._threads(worker)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        stages = [r for r in records if r["event"] == "stage"]
        self.assertEqual(len(stages), 4)
        for record in stages:
            self.assertEqual(f"agent/issue-{record['issue']}", record["detail"])
        self.assertEqual({r["issue"] for r in stages}, {86, 87})

    def test_json_attributes_stage_progress_to_the_right_stage(self):
        stream = io.StringIO()
        ui = ui_mod.JsonUi(stream)

        def worker(number, barrier):
            ui.issue_start(1, 2, number, f"issue {number}")
            stage = Stage.IMPLEMENT if number == 86 else Stage.CI
            ui.stage(stage, Status.RUNNING, "")
            barrier.wait()
            ui.stage_detail(f"detail {number}", key=str(number))

        self._threads(worker)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        progress = {r["issue"]: r for r in records
                    if r["event"] == "stage.progress"}
        self.assertEqual(progress[86]["stage"], "IMPLEMENT")
        self.assertEqual(progress[87]["stage"], "CI")

    def test_the_stage_view_names_the_issue_that_reached_each_stage(self):
        stream = io.StringIO()
        ui = StageUi(stream, level="compact", tty=False, clock=StepClock(),
                     unicode=True, multi=True)

        def worker(number, barrier):
            ui.issue_start(1, 2, number, f"issue {number}")
            barrier.wait()
            ui.stage(Stage.CLAIM, Status.OK, f"agent/issue-{number}")
            barrier.wait()
            ui.stage(Stage.IMPLEMENT, Status.RUNNING, "")
            ui.stage_detail(f"iteration 1/4 of {number}", key=str(number))

        self._threads(worker)
        for line in stream.getvalue().splitlines():
            if " CLAIM" not in line:
                continue
            number = line.split("#", 1)[1].split()[0]
            self.assertIn(f"agent/issue-{number}", line)
        for line in stream.getvalue().splitlines():
            if "iteration 1/4 of" not in line:
                continue
            number = line.split("#", 1)[1].split()[0]
            self.assertIn(f"iteration 1/4 of {number}", line)


class OverlappingRunner(fakes.FakeRunner):
    """Two agentbox runs whose event streams genuinely overlap.

    Neither run may return before both have started, and #86 publishes its
    whole event stream while #87 is still inside its own call. A coordinator
    that kept "which phases has agentbox reported" per PROCESS would then let
    #86's ``implement.done`` answer for #87, and #87 would lose the line that
    says what it produced.
    """

    def __init__(self, git, events_by_issue):
        super().__init__(git)
        self.events_by_issue = events_by_issue
        self.started = threading.Barrier(2, timeout=10)
        self.first_published = threading.Event()

    def run(self, repo, branch, prompt_file, base_ref, continuation=False,
            log_name="agentbox", log_dir="", on_event=None, on_raw=None):
        number = 86 if "issue-86" in branch else 87
        self.calls.append({"branch": branch, "log_dir": log_dir})
        self.started.wait()
        if number == 86:
            for item in self.events_by_issue[86]:
                if on_event is not None:
                    on_event(item)
            self.first_published.set()
        else:
            self.first_published.wait(timeout=10)
            for item in self.events_by_issue[87]:
                if on_event is not None:
                    on_event(item)

        from agentqueue.model import classify_agentbox_exit

        sha = f"sha-{number}"
        self.git.refs[f"refs/heads/{branch}"] = sha
        return fakes.AgentRun(
            exit_code=0,
            outcome=classify_agentbox_exit(0, ""),
            output="",
            summary={
                "checksPassed": True,
                "failedChecks": [],
                "fixRounds": 0,
                "review": {"skipped": True, "reason": "no Codex credential"},
                "resultCommit": sha,
                "commits": ["a"],
            },
            duration_seconds=1,
            command=["agentbox"],
            log_path=os.path.join(log_dir or "/fake", f"{log_name}.log"),
        )


class TestConcurrentDrain(unittest.TestCase):
    """The same defect, through the coordinator, with two issues at once."""

    def _drain(self):
        stream = io.StringIO()
        ui = StageUi(stream, level="compact", tty=False, clock=StepClock(),
                     unicode=True, multi=True)
        github = fakes.FakeGitHub()
        github.add_issue(86, "One", labels=(READY,))
        github.add_issue(87, "Two", labels=(READY,))
        git = fakes.FakeGit()
        policy = fakes.make_policy(
            autoMerge=False, mergeWithoutReview=True, checks=["pnpm check"],
            maxParallel=2,
        )
        # #86 publishes its phases. #87 publishes none, so the coordinator
        # must state #87's result itself.
        runner = OverlappingRunner(git, {86: GREEN_EVENTS, 87: []})
        github.head_sha_source = lambda b: git.refs.get(
            "refs/heads/" + b, "sha-" + b
        )
        github.check_runs = lambda sha: [
            CheckRun("Quality", "completed", "success")
        ]
        coordinator = Coordinator(
            github, git, policy, runner, tempfile.mkdtemp(),
            os.path.join(_ROOT, "bin", "scan-secrets"),
            emit=lambda line: ui.note(line), dry_run=False, run_id="testrun",
            agent_identities=(fakes.AGENT_IDENTITY,),
            sleep=lambda _s: None, ui=ui,
        )
        report = coordinator.drain()
        ui.close()
        return report, stream.getvalue()

    def test_both_issues_report_their_own_implementation(self):
        report, text = self._drain()
        self.assertEqual(
            [r.outcome for r in report.results],
            [Outcome.SUCCESS, Outcome.SUCCESS],
        )
        self.assertEqual([r.issue for r in report.results], [86, 87])
        done = [l for l in text.splitlines() if "IMPLEMENT" in l and "✓" in l]
        # Exactly one finished IMPLEMENT line per issue, each naming its own.
        self.assertEqual(len(done), 2, text)
        self.assertEqual(
            sorted(l.split("#", 1)[1].split()[0] for l in done),
            ["86", "87"],
            text,
        )

    def test_every_stage_line_names_the_issue_it_belongs_to(self):
        _, text = self._drain()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("✓", "-", "●", "!")):
                continue
            self.assertRegex(stripped, r"^[✓\-●!] #(86|87) ", text)

    def test_each_issue_reaches_its_own_position_in_the_counter(self):
        _, text = self._drain()
        headers = [l for l in text.splitlines() if l.startswith("[")]
        self.assertEqual(sorted(headers)[0].split("]")[0], "[1/2")
        self.assertEqual(sorted(headers)[1].split("]")[0], "[2/2")


# ---------------------------------------------------- the child, for real --


HELPER = r'''
import sys
sys.stdout.write("[agentbox] run id 1\n")
sys.stdout.write('===AGENTBOX_EVENT=== {"event": "implement.start", "agent": "claude"}\n')
sys.stdout.write("some model output\n")
sys.stdout.write('===AGENTBOX_EVENT=== {"event": "implement.done", "commits": 2}\n')
sys.stdout.write("\n===AGENTBOX_SUMMARY_JSON===\n")
sys.stdout.write('{"checksPassed": true, "resultCommit": "abc", "commits": ["a", "b"]}\n')
sys.stdout.write("===END===\n")
sys.stdout.flush()
sys.exit(int(sys.argv[1]))
'''


class FakeAgentbox:
    """A real child process that speaks the agentbox protocol."""

    def __init__(self, tmp, exit_code=0):
        self.path = os.path.join(tmp, "fake-agentbox")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexec %s -c '%s' \"$4\"\n" % (
                sys.executable, HELPER.replace("'", "'\\''")))
        os.chmod(self.path, 0o755)
        self.exit_code = exit_code


class TestRunnerContract(unittest.TestCase):
    """The new layer must change nothing the coordinator depends on."""

    def _run(self, exit_code, level_events=None):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "child.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(HELPER)
        shim = os.path.join(tmp, "agentbox")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(
                f"#!/bin/sh\nexec {sys.executable} {script} {exit_code}\n"
            )
        os.chmod(shim, 0o755)
        prompt = os.path.join(tmp, "p.md")
        with open(prompt, "w", encoding="utf-8") as handle:
            handle.write("do the thing")
        runner = AgentboxRunner(
            shim, fakes.make_policy(checks=["pnpm check"]), os.path.join(tmp, "logs")
        )
        events, raw = [], []
        run = runner.run(
            "/repo", "agent/issue-1", prompt, "refs/remotes/origin/main",
            log_name="implement", on_event=events.append, on_raw=raw.append,
        )
        return run, events, raw, tmp

    def test_the_child_exit_code_is_preserved(self):
        for code in (0, 8, 9, 11):
            run, _, _, _ = self._run(code)
            self.assertEqual(run.exit_code, code)

    def test_the_summary_block_is_still_parsed(self):
        run, _, _, _ = self._run(0)
        self.assertTrue(run.checks_passed)
        self.assertEqual(run.result_commit, "abc")
        self.assertIs(run.outcome, Outcome.SUCCESS)

    def test_the_events_reach_the_caller_and_never_the_raw_stream(self):
        _, events, raw, _ = self._run(0)
        self.assertEqual([e["event"] for e in events],
                         ["implement.start", "implement.done"])
        self.assertNotIn("===AGENTBOX_EVENT===", "\n".join(raw))
        self.assertIn("some model output", raw)

    def test_every_line_is_written_to_the_run_log(self):
        run, _, _, _ = self._run(0)
        with open(run.log_path, "r", encoding="utf-8") as handle:
            log = handle.read()
        self.assertIn("some model output", log)
        self.assertIn("===AGENTBOX_EVENT===", log)
        self.assertIn("===AGENTBOX_SUMMARY_JSON===", log)
        self.assertEqual(os.stat(run.log_path).st_mode & 0o777, 0o600)

    def test_the_command_still_carries_every_bound(self):
        policy = fakes.make_policy(checks=["pnpm check"])
        runner = AgentboxRunner("/bin/agentbox", policy, "/logs")
        cmd = runner.command("/repo", "agent/issue-1", "/p.md",
                             "refs/remotes/origin/main")
        for flag in ("--timeout", "--max-commits", "--max-iterations",
                     "--max-fix-rounds", "--prompt-file", "--branch", "--repo"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[1], "pipeline")
        self.assertIn("--agent-output", cmd)
        self.assertEqual(cmd[cmd.index("--agent-output") + 1], "progress")

    def test_debug_asks_agentbox_for_its_own_terminal_output(self):
        runner = AgentboxRunner("/bin/agentbox", fakes.make_policy(), "/logs",
                                agent_output="terminal")
        cmd = runner.command("/repo", "agent/issue-1", "/p.md", "refs/x")
        self.assertEqual(cmd[cmd.index("--agent-output") + 1], "terminal")

    def test_an_integrity_marker_still_stops_the_queue(self):
        run, _, _, _ = self._run(0)
        self.assertIs(run.outcome, Outcome.SUCCESS)
        from agentqueue.model import classify_agentbox_exit
        self.assertIs(
            classify_agentbox_exit(0, "DISPOSABLE CLONE INTEGRITY FAILED: 1"),
            Outcome.SECURITY_OR_INTEGRITY_FAILURE,
        )


class TestInterrupt(unittest.TestCase):
    """Ctrl-C must reach the caller, and the evidence must survive it."""

    def test_an_interrupt_in_the_display_reaches_the_caller(self):
        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "child.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(HELPER)
        shim = os.path.join(tmp, "agentbox")
        with open(shim, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\nexec {sys.executable} {script} 0\n")
        os.chmod(shim, 0o755)
        prompt = os.path.join(tmp, "p.md")
        with open(prompt, "w", encoding="utf-8") as handle:
            handle.write("x")
        runner = AgentboxRunner(shim, fakes.make_policy(), os.path.join(tmp, "logs"))

        def interrupt(_line):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            runner.run("/repo", "agent/issue-1", prompt, "refs/x",
                       log_name="implement", on_raw=interrupt)
        # The log was opened before the first line and holds what arrived.
        log = os.path.join(tmp, "logs", "implement.log")
        self.assertTrue(os.path.exists(log))
        with open(log, "r", encoding="utf-8") as handle:
            self.assertIn("[agentbox] run id 1", handle.read())

    def test_closing_the_display_ends_the_active_line(self):
        stream = io.StringIO()
        ui = StageUi(stream, level="compact", tty=True, clock=StepClock(),
                     unicode=True)
        ui.issue_start(1, 1, 86, "One")
        ui.stage(Stage.IMPLEMENT, Status.RUNNING, "Claude")
        self.assertFalse(stream.getvalue().endswith("\n"))
        ui.close()
        self.assertTrue(stream.getvalue().endswith("\n"))

    def test_closing_the_display_twice_is_harmless(self):
        ui = StageUi(io.StringIO(), level="compact", tty=False)
        ui.close()
        ui.close()

    def test_the_heartbeat_thread_stops_when_the_display_closes(self):
        ui = StageUi(io.StringIO(), level="compact", tty=False,
                     refresh_seconds=0.01, heartbeat_seconds=0.01)
        ui.start()
        thread = ui._thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon)
        ui.close()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
