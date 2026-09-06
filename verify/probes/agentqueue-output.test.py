#!/usr/bin/env python3
"""Deterministic tests for what agentqueue prints.

No network, no container, no model and no real clock. The agent is a scripted
event stream, the terminal is a string buffer, and time is a counter. Every
case below therefore gives the same answer on every machine.

    python3 verify/probes/agentqueue-output.test.py

verify/85-agentq.sh runs this file, and it fails the module on any error.

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
    two issues at a time never interleave one another's blocks, on the
        terminal or in the evidence log
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import agentqueue_fakes as fakes  # noqa: E402
from agentqueue import VERSION, ui as ui_mod  # noqa: E402
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
     "maxIterations": 1},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 1, "tools": 3},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 1, "tools": 9},
    {"event": "implement.done", "commits": 1, "iterations": 1},
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
    """One scripted run, rendered into a string."""

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

    def run(self):
        coordinator = Coordinator(
            self.github, self.git, self.policy, self.runner, self._tmp,
            os.path.join(_ROOT, "bin", "scan-secrets"),
            emit=lambda line: self.ui.note(line), dry_run=False,
            run_id="testrun", run_log="/state/runs/testrun/queue.log",
            agent_identities=(fakes.AGENT_IDENTITY,),
            sleep=lambda _s: None, ui=self.ui,
        )
        report = coordinator.run()
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
        harness.run()
        self.assertIn(f"agentq {VERSION}", harness.lines[0])
        self.assertIn("acme/widget · 1 runnable issue · sequential", harness.text)

    def test_the_issue_carries_its_position_and_its_title(self):
        harness = Harness(
            script=[green(), green(sha="sha-87")],
            issues=[(86, "Implement entry-selection module"),
                    (87, "Implement validate-content rule-checker split")],
        )
        harness.run()
        self.assertIn("[1/2] #86 Implement entry-selection module", harness.text)
        self.assertIn("[2/2] #87 Implement validate-content rule-checker split",
                      harness.text)

    def test_the_stages_appear_in_lifecycle_order(self):
        harness = Harness(script=[green()])
        harness.run()
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
        harness.run()
        self.assertIn("- REVIEW", harness.text)
        self.assertIn("skipped · no Codex credential", harness.text)
        # It must never read as a review that ran.
        self.assertNotIn("✓ REVIEW", harness.text)

    def test_a_passing_local_check_is_reported_with_its_duration(self):
        harness = Harness(script=[green()])
        harness.run()
        check = [l for l in harness.stage_lines() if l.startswith("✓ CHECK")]
        self.assertEqual(len(check), 1)
        self.assertIn("1 check passed", check[0])
        self.assertRegex(check[0], r"\d+s")

    def test_agent_progress_is_the_real_iteration_not_a_percentage(self):
        harness = Harness(script=[green()])
        harness.run()
        self.assertIn("iteration 1/1", harness.text)
        self.assertIn("tool calls", harness.text)
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
        harness.run()
        self.assertIn("● CI", harness.text)
        self.assertIn("pending: Quality", harness.text)
        self.assertIn("✓ CI", harness.text)
        self.assertIn("1 check passed", harness.text)

    def test_the_final_summary_names_every_issue_and_counts_them(self):
        harness = Harness(
            script=[green(), green(sha="sha-87")],
            issues=[(86, "One"), (87, "Two")],
        )
        harness.run()
        self.assertIn("agentq complete", harness.text)
        self.assertRegex(harness.text, r"✓ #86 → PR #\d+ merged")
        self.assertRegex(harness.text, r"✓ #87 → PR #\d+ merged")
        self.assertIn("2 completed · 0 failed · 0 human intervention", harness.text)

    def test_no_raw_child_output_reaches_a_compact_terminal(self):
        noise = [f"thinking about line {n}" for n in range(300)]
        harness = Harness(script=[green(raw=noise)])
        harness.run()
        self.assertNotIn("thinking about line", harness.text)
        # It is not lost: the transcript holds every one of them.
        self.assertIn("thinking about line 299", "\n".join(harness.transcript))

    def test_a_compact_run_stays_short(self):
        noise = [f"tool call {n}" for n in range(500)]
        harness = Harness(script=[green(raw=noise)])
        harness.run()
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
        harness.run()
        self.assertIn("✗ CHECK", harness.text)
        self.assertIn("pnpm check", harness.text)
        self.assertIn("Last output:", harness.text)
        self.assertIn("Expected 3 entries, received 2", harness.text)
        self.assertIn("→ retry 1/2", harness.text)
        self.assertIn("→ retry 2/2", harness.text)

    def test_a_failure_names_the_log_that_holds_the_whole_output(self):
        harness = Harness(script=self._failing_check_script())
        harness.run()
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
        harness.run()
        blocks = harness.text.count("Last output:")
        shown = [l for l in harness.lines if "failure line" in l]
        self.assertGreaterEqual(blocks, 1)
        self.assertLessEqual(len(shown), 12 * blocks)
        self.assertIn("failure line 399", harness.text)
        self.assertNotIn("failure line 0\n", harness.text)

    def test_an_exhausted_retry_budget_asks_for_a_human(self):
        harness = Harness(script=self._failing_check_script())
        report = harness.run()
        self.assertIn("! NEEDS_HUMAN", harness.text)
        self.assertIs(report.results[0].outcome, Outcome.NEEDS_HUMAN)
        self.assertIn("1 human intervention", harness.text)

    def test_an_agentbox_failure_states_the_exit_code(self):
        harness = Harness(script=[{"exit": 8, "output": "the agent gave up"}])
        report = harness.run()
        self.assertIn("✗ IMPLEMENT", harness.text)
        self.assertIn("agentbox exited 8", harness.text)
        self.assertIs(report.results[0].outcome, Outcome.FAILED_TRANSIENT)

    def test_a_security_failure_is_not_dressed_as_a_failing_test(self):
        harness = Harness(script=[{
            "exit": 9,
            "output": "DISPOSABLE CLONE INTEGRITY FAILED: 2 change(s)",
        }])
        report = harness.run()
        self.assertTrue(report.stopped_for_security)
        self.assertIn("⚠ SECURITY", harness.text)
        self.assertIn("a security or integrity failure, not a failing test",
                      harness.text)
        self.assertIn("THE QUEUE STOPPED", harness.text)
        self.assertIn("agentq stopped", harness.text)
        # An ordinary failure marker must not be the only thing a reader sees.
        self.assertNotIn("agentq complete", harness.text)

    def test_a_credential_in_the_diff_stops_the_queue_visibly(self):
        harness = Harness(script=[green()])
        harness.git.diffs["agent/issue-86-implement-entry-selection-module"] = (
            "+const key = 'AKIA" + "0123456789ABCDEF';\n"
        )
        report = harness.run()
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
        harness.run()
        self.assertNotIn("✓ CLAIM", harness.text)
        self.assertNotIn("● IMPLEMENT", harness.text)
        self.assertNotIn("a model sentence", harness.text)
        self.assertNotIn("== agentq summary ==", harness.text)
        self.assertIn("agentq complete", harness.text)
        self.assertIn("1 completed", harness.text)

    def test_quiet_still_shows_a_failure(self):
        harness = Harness(level="quiet",
                          script=[{"exit": 8, "output": "the agent gave up"}])
        harness.run()
        self.assertIn("✗ IMPLEMENT", harness.text)
        self.assertIn("agentbox exited 8", harness.text)

    def test_quiet_still_shows_a_security_stop(self):
        harness = Harness(level="quiet", script=[{
            "exit": 9, "output": "DISPOSABLE CLONE INTEGRITY FAILED: 1 change",
        }])
        harness.run()
        self.assertIn("⚠ SECURITY", harness.text)
        self.assertIn("THE QUEUE STOPPED", harness.text)

    def test_verbose_adds_the_coordinator_notes_and_keeps_the_stages(self):
        harness = Harness(level="verbose", script=self._script())
        harness.run()
        self.assertIn("✓ CLAIM", harness.text)
        self.assertIn("wave 1: #86", harness.text)
        self.assertIn("pull request #501", harness.text)
        self.assertIn("== agentq summary ==", harness.text)
        # Verbose is not debug: the model's own sentences stay out.
        self.assertNotIn("a model sentence", harness.text)

    def test_debug_adds_every_raw_line(self):
        harness = Harness(level="debug", script=self._script())
        harness.run()
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
                            ["run", "--repo", ".", first, second]
                        )
                    finally:
                        sys.stderr = stderr

    def test_each_output_mode_is_accepted_on_its_own(self):
        from agentqueue.cli import build_parser

        parser = build_parser()
        for flag in ("--quiet", "--verbose", "--debug", "--json"):
            args = parser.parse_args(["run", "--repo", ".", flag])
            self.assertTrue(
                args.quiet or args.verbose or args.debug or args.json_out
            )


class TestJsonOutput(unittest.TestCase):
    def test_every_event_is_one_json_object(self):
        stream = io.StringIO()
        ui = ui_mod.JsonUi(stream)
        harness = Harness(script=[green()])
        harness.ui = ui
        report = harness.run()
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
        harness.run()
        self.assertNotIn("\x1b", stream.getvalue())
        self.assertNotIn("\r", stream.getvalue())


# ------------------------------------------------------------- the terminal --


class TestTerminalBehaviour(unittest.TestCase):
    def test_a_redirected_stream_receives_no_control_sequence(self):
        harness = Harness(tty=False, script=[green()])
        harness.run()
        self.assertNotIn("\x1b", harness.text)
        self.assertNotIn("\r", harness.text)

    def test_a_redirected_stream_keeps_one_line_per_transition(self):
        harness = Harness(tty=False, script=[green()])
        harness.run()
        for line in harness.lines:
            self.assertEqual(line, line.rstrip())
        self.assertGreater(len([l for l in harness.lines if l.startswith("  ")]), 5)

    def test_an_interactive_terminal_repaints_the_active_line(self):
        harness = Harness(tty=True, script=[green()])
        harness.run()
        self.assertIn("\r\x1b[2K", harness.text)

    def test_an_interactive_terminal_and_a_file_carry_the_same_lines(self):
        def rendered(tty):
            harness = Harness(tty=tty, script=[green()], clock=StepClock())
            harness.run()
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
        harness.run()
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
        harness.run()
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
        harness.run()
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


class YieldingStream:
    """A stream that lets the scheduler switch on every write.

    ``io.StringIO`` is effectively atomic per call under the GIL, so a test
    that used one would pass whether or not the renderer holds its lock. This
    one sleeps between writes, which is what a real terminal or a real file
    does under contention. An unserialised writer then interleaves every time,
    and a serialised one cannot interleave at all.
    """

    encoding = "utf-8"

    def __init__(self, delay=0.002):
        self.delay = delay
        self._chunks = []
        self._guard = threading.Lock()   # protects the list, nothing else

    def write(self, text):
        with self._guard:
            self._chunks.append(text)
        time.sleep(self.delay)

    def flush(self):
        pass

    def isatty(self):
        return False

    def getvalue(self):
        with self._guard:
            return "".join(self._chunks)


class TestConcurrentSerialisation(unittest.TestCase):
    """A block written by one issue is never split by another.

    Attribution says which issue a line belongs to. This says that the lines
    of one block arrive together. A failure block whose evidence had another
    issue's progress line in the middle of it would be worse than no block:
    a reader would attach the wrong output to the wrong failure.
    """

    MARKS = ("MARK-86", "MARK-87")

    def _run_in_two_threads(self, worker, timeout=15):
        errors = []

        def guarded(mark):
            try:
                worker(mark)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=guarded, args=(m,))
                   for m in self.MARKS]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=timeout)
            self.assertFalse(thread.is_alive(), "a worker did not finish")
        self.assertEqual(errors, [])

    def _assert_blocks_are_contiguous(self, text, first, last):
        """Between one mark's first and last line, no other mark appears."""
        lines = text.splitlines()
        for mine in self.MARKS:
            others = [m for m in self.MARKS if m != mine]
            starts = [i for i, l in enumerate(lines) if first(mine) in l]
            ends = [i for i, l in enumerate(lines) if last(mine) in l]
            self.assertEqual(len(starts), 1, f"{mine}\n{text}")
            self.assertEqual(len(ends), 1, f"{mine}\n{text}")
            self.assertLess(starts[0], ends[0], text)
            for line in lines[starts[0]:ends[0] + 1]:
                for other in others:
                    self.assertNotIn(other, line, f"interleaved:\n{text}")

    def test_a_failure_block_is_never_split_by_another_issue(self):
        stream = YieldingStream()
        ui = StageUi(stream, level="compact", tty=False, clock=StepClock(),
                     unicode=True, multi=True)

        def worker(mark):
            ui.failure(
                Stage.CHECK, f"pnpm check {mark}",
                tail=[f"evidence {mark} line {i}" for i in range(5)],
                log_path=f"/logs/{mark}.log",
                retry=f"retry 1/2 {mark}",
            )

        self._run_in_two_threads(worker)
        self._assert_blocks_are_contiguous(
            stream.getvalue(),
            lambda m: f"pnpm check {m}",
            lambda m: f"retry 1/2 {m}",
        )

    def test_an_issue_frame_is_never_split_by_another_issue(self):
        stream = YieldingStream()
        ui = StageUi(stream, level="verbose", tty=False, clock=StepClock(),
                     unicode=True, multi=True)

        def worker(mark):
            number = int(mark.split("-")[1])
            ui.issue_start(1, 2, number, f"title {mark}")
            ui.note(f"note {mark}", level="verbose")
            ui.stage(Stage.CLAIM, Status.OK, f"branch {mark}")
            ui.issue_end(number, Status.OK, f"finished {mark}")

        self._run_in_two_threads(worker)
        # Each thread's own lines must not be torn apart mid-line.
        for line in stream.getvalue().splitlines():
            present = [m for m in self.MARKS if m in line]
            self.assertLessEqual(len(present), 1, f"torn line: {line!r}")

    def test_the_evidence_log_receives_each_block_whole(self):
        """The canonical run log, written from two threads through a real file."""
        from agentqueue.cli import _RunLog

        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "runs", "testrun", "queue.log")
        run_log = _RunLog(path)
        self.assertTrue(os.path.exists(path))
        stream = YieldingStream()
        ui = StageUi(stream, level="quiet", tty=False, clock=StepClock(),
                     unicode=True, multi=True, transcript=run_log.write)

        def worker(mark):
            ui.failure(
                Stage.CHECK, f"pnpm check {mark}",
                tail=[f"evidence {mark} line {i}" for i in range(5)],
                retry=f"retry 1/2 {mark}",
            )

        self._run_in_two_threads(worker)
        run_log.close()
        with open(path, "r", encoding="utf-8") as handle:
            written = handle.read()
        self._assert_blocks_are_contiguous(
            written,
            lambda m: f"pnpm check {m}",
            lambda m: f"retry 1/2 {m}",
        )
        # A quiet terminal printed the failure and nothing else; the log has
        # the same block. The level changed the terminal, not the evidence.
        self.assertIn("evidence MARK-86 line 4", written)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_the_evidence_log_loses_no_line_under_several_writers(self):
        from agentqueue.cli import _RunLog

        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "queue.log")
        run_log = _RunLog(path)
        writers, per_writer = 4, 60
        expected = {
            f"writer {w} line {i}"
            for w in range(writers) for i in range(per_writer)
        }

        def worker(index):
            for i in range(per_writer):
                run_log.write(f"writer {index} line {i}")

        threads = [threading.Thread(target=worker, args=(w,))
                   for w in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        run_log.close()
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        # Every line is whole, none is lost, and none was written twice.
        self.assertEqual(len(lines), writers * per_writer)
        self.assertEqual(set(lines), expected)

    def test_a_closed_run_log_refuses_a_late_write(self):
        from agentqueue.cli import _RunLog

        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "queue.log")
        run_log = _RunLog(path)
        run_log.write("before")
        run_log.close()
        run_log.write("after")          # must not raise, and must not appear
        run_log.close()                 # closing twice is harmless
        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read().splitlines(), ["before"])

    def test_the_json_stream_writes_one_whole_object_per_line(self):
        stream = YieldingStream()
        ui = ui_mod.JsonUi(stream)

        def worker(mark):
            number = int(mark.split("-")[1])
            ui.issue_start(1, 2, number, f"title {mark}")
            for stage in (Stage.CLAIM, Stage.PUSH, Stage.PR):
                ui.stage(stage, Status.OK, f"detail {mark}")
            ui.issue_end(number, Status.OK, f"done {mark}")

        self._run_in_two_threads(worker)
        for line in stream.getvalue().splitlines():
            record = json.loads(line)          # a torn line fails here
            self.assertIn("event", record)


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
            log_name="agentbox", log_dir="", on_event=None, on_raw=None,
            effort=None):
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

    def _run(self):
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
        report = coordinator.run()
        ui.close()
        return report, stream.getvalue()

    def test_both_issues_report_their_own_implementation(self):
        report, text = self._run()
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
        _, text = self._run()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("✓", "-", "●", "!")):
                continue
            self.assertRegex(stripped, r"^[✓\-●!] #(86|87) ", text)

    def test_each_issue_reaches_its_own_position_in_the_counter(self):
        _, text = self._run()
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


# ---------------------------------------------- the efficiency budget line --


#: The events an expensive-but-healthy invocation publishes. The soft warning
#: arrives between two progress lines, and it must stay on the line after it.
WARNED_EVENTS = [
    {"event": "implement.start", "agent": "claude", "model": "opus",
     "maxIterations": 1},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 1, "tools": 12},
    {"event": "budget.warning", "phase": "implement", "seconds": 600,
     "tools": 30,
     "breaches": [{"metric": "seconds", "level": "soft",
                   "limit": 600, "value": 600}]},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 1, "tools": 31},
    {"event": "implement.done", "commits": 1, "iterations": 1},
    {"event": "check.start", "command": "pnpm check", "index": 1, "total": 1},
    {"event": "checks.done", "total": 1, "failed": 0},
    {"event": "review.skipped", "reason": "no Codex credential"},
    {"event": "integrity.ok"},
    {"event": "import.done", "commits": 1, "tip": "deadbeefcafe"},
]

#: The events a stopped invocation publishes before agentbox exits 12.
EXCEEDED_EVENTS = [
    {"event": "implement.start", "agent": "claude", "model": "opus",
     "maxIterations": 1},
    {"event": "agent.progress", "phase": "implement", "agent": "claude",
     "iteration": 1, "maxIterations": 1, "tools": 40},
    {"event": "budget.exceeded", "phase": "implement", "seconds": 640,
     "tools": 60,
     "breaches": [{"metric": "toolCalls", "level": "hard",
                   "limit": 60, "value": 60}]},
]


class TestBudgetOutput(unittest.TestCase):
    def test_a_soft_breach_shows_a_warning_and_the_run_continues(self):
        harness = Harness(script=[green(events=WARNED_EVENTS)])
        report = harness.run()
        self.assertIn("efficiency warning", harness.text)
        self.assertIn("600s of model time (limit 600s)", harness.text)
        # The warning stays on the line the next progress event paints.
        self.assertRegex(harness.text, r"31 tool calls.*efficiency warning")
        self.assertIs(report.results[0].outcome, Outcome.SUCCESS)

    def test_a_healthy_run_never_says_efficiency_warning(self):
        harness = Harness(script=[green()])
        harness.run()
        self.assertNotIn("efficiency warning", harness.text)
        self.assertNotIn("over budget", harness.text)

    def test_a_hard_breach_says_what_was_passed_and_imports_nothing(self):
        step = {
            "events": EXCEEDED_EVENTS,
            "exit": 12,
            "summary": {
                "checksPassed": None,
                "efficiency": {"seconds": 640, "invocations": 1,
                               "toolCalls": 60, "tokens": None,
                               "warnings": [], "exceeded": {"phase": "implement"}},
                "budgetExceeded": {
                    "phase": "implement", "seconds": 640, "toolCalls": 60,
                    "breaches": [{"metric": "toolCalls", "level": "hard",
                                  "limit": 60, "value": 60}],
                },
            },
            "output": "agentbox: one model invocation passed its efficiency budget",
        }
        harness = Harness(script=[step])
        report = harness.run()
        self.assertIn("over budget", harness.text)
        self.assertIn("60 tool calls (limit 60)", harness.text)
        self.assertIn("nothing imported", harness.text)
        self.assertIs(report.results[0].outcome, Outcome.BUDGET_EXCEEDED)
        self.assertNotIn("✓ IMPORT", harness.text)
        self.assertNotIn("✓ MERGE", harness.text)

    def test_the_closing_summary_counts_a_breach_on_its_own_line(self):
        step = {
            "events": EXCEEDED_EVENTS,
            "exit": 12,
            "summary": {
                "checksPassed": None,
                "efficiency": {"seconds": 640, "invocations": 1,
                               "toolCalls": 60, "tokens": None,
                               "warnings": [], "exceeded": {"phase": "implement"}},
                "budgetExceeded": {
                    "phase": "implement", "seconds": 640, "toolCalls": 60,
                    "breaches": [{"metric": "toolCalls", "level": "hard",
                                  "limit": 60, "value": 60}],
                },
            },
            "output": "",
        }
        harness = Harness(script=[step])
        report = harness.run()
        # The compact counts name it only when it happened.
        self.assertIn("1 over budget", harness.text)
        # The verbose summary always carries the count.
        from agentqueue import report as report_mod

        lines = report_mod.render_summary(report, harness.policy)
        self.assertIn("  issues over budget        1", lines)

    def test_a_green_run_does_not_mention_a_budget_count(self):
        harness = Harness(script=[green()])
        report = harness.run()
        self.assertNotIn("over budget", harness.text)
        from agentqueue import report as report_mod

        self.assertIn(
            "  issues over budget        0",
            report_mod.render_summary(report, harness.policy),
        )

    def test_a_breach_is_not_also_reported_as_a_crash(self):
        step = {
            "events": EXCEEDED_EVENTS,
            "exit": 12,
            "summary": {
                "checksPassed": None,
                "efficiency": {},
                "budgetExceeded": {
                    "phase": "implement", "seconds": 640, "toolCalls": 60,
                    "breaches": [{"metric": "toolCalls", "level": "hard",
                                  "limit": 60, "value": 60}],
                },
            },
            "output": "",
        }
        harness = Harness(script=[step])
        harness.run()
        self.assertNotIn("agentbox exited 12", harness.text)
        self.assertIn("over budget", harness.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
