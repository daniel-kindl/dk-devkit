#!/usr/bin/env python3
"""Deterministic tests for model routing.

No network, no container, no model. Every case reads the real catalog in
manifests/model-tiers.json, or a small catalog written into a temporary file,
and every answer is the same on every machine.

    python3 verify/probes/agentqueue-effort.test.py

verify/85-agentq.sh runs this file, and it fails the module on any error.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "lib"))

import agentqueue_fakes as fakes  # noqa: E402
from agentqueue import effort as effort_mod  # noqa: E402
from agentqueue.coordinator import Coordinator, _agent_label  # noqa: E402
from agentqueue.model import Issue, Outcome  # noqa: E402
from agentqueue.runner import AgentboxRunner  # noqa: E402

CATALOG_PATH = effort_mod.manifest_path(_ROOT)


def issue(number=1, title="Add a helper", body="", labels=()):
    return Issue(number=number, title=title, body=body, state="open", labels=tuple(labels))


def write_catalog(directory, mutate=None):
    with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    document = copy.deepcopy(document)
    if mutate is not None:
        mutate(document)
    path = os.path.join(directory, "tiers.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    return path


# ------------------------------------------------------------------ catalog --


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.catalog = effort_mod.load(CATALOG_PATH)

    def test_the_repository_catalog_defines_three_tiers(self):
        self.assertEqual(
            [tier.id for tier in self.catalog.tiers],
            ["lightweight", "standard", "hard"],
        )

    def test_the_markers_are_l_s_and_h(self):
        self.assertEqual([tier.marker for tier in self.catalog.tiers], ["L", "S", "H"])

    def test_every_tier_pins_an_exact_model_id(self):
        for tier in self.catalog.tiers:
            for role in (tier.implementer, tier.reviewer):
                self.assertTrue(role.model.strip(), tier.id)
                self.assertNotEqual(role.model, role.family)

    def test_no_model_reviews_its_own_implementation(self):
        for tier in self.catalog.tiers:
            self.assertNotEqual(tier.implementer.agent, tier.reviewer.agent, tier.id)

    def test_the_default_names_a_tier_that_exists(self):
        self.assertTrue(self.catalog.has(self.catalog.default))

    def test_a_same_provider_pairing_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            def mutate(document):
                document["tiers"][1]["reviewer"]["agent"] = \
                    document["tiers"][1]["implementer"]["agent"]

            path = write_catalog(tmp, mutate)
            with self.assertRaises(effort_mod.EffortError) as caught:
                effort_mod.load(path)
            self.assertIn("different", str(caught.exception))

    def test_a_default_that_names_no_tier_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_catalog(tmp, lambda d: d.update(default="enormous"))
            with self.assertRaises(effort_mod.EffortError):
                effort_mod.load(path)

    def test_two_tiers_may_not_share_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            def mutate(document):
                document["tiers"][0]["marker"] = document["tiers"][1]["marker"]

            path = write_catalog(tmp, mutate)
            with self.assertRaises(effort_mod.EffortError):
                effort_mod.load(path)

    def test_an_unknown_version_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_catalog(tmp, lambda d: d.update(version=2))
            with self.assertRaises(effort_mod.EffortError):
                effort_mod.load(path)

    def test_a_missing_catalog_is_refused_rather_than_guessed_at(self):
        with self.assertRaises(effort_mod.EffortError):
            effort_mod.load("/nonexistent/tiers.json")

    def test_a_taxonomy_label_may_not_name_an_unknown_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            def mutate(document):
                document["signals"]["byLabel"]["documentation"] = "trivial"

            path = write_catalog(tmp, mutate)
            with self.assertRaises(effort_mod.EffortError):
                effort_mod.load(path)


# --------------------------------------------------------------- the rules --


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.catalog = effort_mod.load(CATALOG_PATH)
        self.policy = fakes.make_policy()

    def resolve(self, subject, attempt=0, **overrides):
        policy = fakes.make_policy(**overrides)
        return effort_mod.resolve(subject, policy, self.catalog, attempt=attempt)

    # --- the ordinary path --------------------------------------------------

    def test_an_unlabelled_issue_gets_the_default_tier(self):
        decision = self.resolve(issue(title="Add a helper"))
        self.assertEqual(decision.id, "standard")
        self.assertEqual(decision.marker, "S")
        self.assertEqual(decision.rule, "the catalog default")

    def test_the_standard_tier_pairs_two_providers(self):
        decision = self.resolve(issue())
        self.assertEqual(decision.implementer.agent, "claude")
        self.assertEqual(decision.reviewer.agent, "codex")

    def test_documentation_is_lightweight(self):
        decision = self.resolve(issue(title="Fix a typo", labels=("documentation",)))
        self.assertEqual(decision.id, "lightweight")
        self.assertEqual(decision.marker, "L")

    def test_a_bug_is_standard(self):
        decision = self.resolve(issue(title="Fix the off by one", labels=("bug",)))
        self.assertEqual(decision.id, "standard")

    def test_the_broadest_taxonomy_label_wins(self):
        decision = self.resolve(
            issue(title="Rename a helper", labels=("documentation", "refactor"))
        )
        self.assertEqual(decision.id, "standard")

    # --- escalation ---------------------------------------------------------

    def test_the_security_label_is_hard(self):
        decision = self.resolve(issue(title="Tidy a helper", labels=("security",)))
        self.assertEqual(decision.id, "hard")
        self.assertEqual(decision.marker, "H")

    def test_a_sensitive_title_beats_a_lightweight_label(self):
        decision = self.resolve(
            issue(title="Document the credential store", labels=("documentation",))
        )
        self.assertEqual(decision.id, "hard")
        self.assertIn("escalate word: credential", decision.signals)

    def test_a_word_matches_only_on_a_word_boundary(self):
        decision = self.resolve(issue(title="Say ciao in the banner"))
        self.assertEqual(decision.id, "standard")

    def test_broad_acceptance_criteria_make_a_task_hard(self):
        body = "\n".join(f"- [ ] item {n}" for n in range(6))
        decision = self.resolve(issue(title="Add a helper", body=body))
        self.assertEqual(decision.id, "hard")
        self.assertIn("acceptance criteria: 6", decision.signals)

    def test_a_short_list_of_criteria_does_not_escalate(self):
        body = "\n".join(f"- [ ] item {n}" for n in range(3))
        decision = self.resolve(issue(title="Add a helper", body=body))
        self.assertEqual(decision.id, "standard")

    # --- explicit intent ----------------------------------------------------

    def test_an_effort_label_pins_the_tier(self):
        decision = self.resolve(issue(title="Add a helper", labels=("effort:hard",)))
        self.assertEqual(decision.id, "hard")
        self.assertIn("effort:hard", decision.rule)

    def test_an_effort_label_overrides_an_escalation_signal(self):
        decision = self.resolve(
            issue(title="Rotate the token", labels=("security", "effort:lightweight"))
        )
        self.assertEqual(decision.id, "lightweight")

    def test_an_unknown_effort_label_is_refused_rather_than_guessed_at(self):
        with self.assertRaises(effort_mod.EffortError):
            self.resolve(issue(labels=("effort:enormous",)))

    def test_a_pinned_policy_beats_every_signal(self):
        decision = self.resolve(
            issue(title="Rotate the token", labels=("security", "effort:hard")),
            effortMode="fixed", effort="lightweight",
        )
        self.assertEqual(decision.id, "lightweight")
        self.assertEqual(decision.signals, ("policy: fixed",))

    # --- evidence-driven escalation ----------------------------------------

    def test_a_failed_attempt_raises_the_tier(self):
        first = self.resolve(issue(title="Add a helper"))
        second = self.resolve(issue(title="Add a helper"), attempt=1)
        self.assertEqual(first.id, "standard")
        self.assertEqual(second.id, "hard")
        self.assertIn("attempt 1", second.signals)

    def test_escalation_stops_at_the_top_tier(self):
        decision = self.resolve(issue(title="Add a helper"), attempt=5)
        self.assertEqual(decision.id, "hard")

    def test_escalation_on_retry_can_be_turned_off(self):
        decision = self.resolve(
            issue(title="Add a helper"), attempt=2, escalateEffortOnRetry=False
        )
        self.assertEqual(decision.id, "standard")

    def test_a_pinned_tier_is_not_raised_by_a_failed_attempt(self):
        decision = self.resolve(
            issue(labels=("effort:lightweight",)), attempt=3
        )
        self.assertEqual(decision.id, "lightweight")

    # --- the decision explains itself --------------------------------------

    def test_the_decision_names_the_rule_that_decided_it(self):
        decision = self.resolve(issue(title="Tidy a helper", labels=("security",)))
        self.assertTrue(decision.rule)
        self.assertIn("H hard", decision.render())

    def test_the_decision_serialises_the_pinned_ids(self):
        record = self.resolve(issue()).as_dict()
        self.assertEqual(record["tier"], "standard")
        self.assertEqual(record["implementer"]["agent"], "claude")
        self.assertTrue(record["implementer"]["model"])
        self.assertTrue(record["reviewer"]["model"])

    def test_classification_never_edits_the_policy(self):
        policy = fakes.make_policy()
        before = policy.as_dict()
        effort_mod.resolve(issue(labels=("security",)), policy, self.catalog, attempt=2)
        self.assertEqual(policy.as_dict(), before)

    def test_a_lower_tier_does_not_weaken_a_merge_gate(self):
        # The tier chooses a model. It touches no gate, so the fields that
        # decide a merge read the same for every tier.
        policy = fakes.make_policy()
        gates = ("reviewPolicy", "mergeWithoutReview", "autoMerge",
                 "requireCiChecks", "scanDiffForSecrets", "maxCommits")
        wanted = {name: getattr(policy, name) for name in gates}
        for subject in (
            issue(labels=("documentation",)),
            issue(labels=("security",)),
            issue(labels=("effort:lightweight",)),
        ):
            effort_mod.resolve(subject, policy, self.catalog)
            self.assertEqual({n: getattr(policy, n) for n in gates}, wanted)


# --------------------------------------------------------- the agentbox call --


class TestTheCommand(unittest.TestCase):
    def setUp(self):
        self.catalog = effort_mod.load(CATALOG_PATH)
        self.policy = fakes.make_policy()

    def command_for(self, decision, **overrides):
        policy = fakes.make_policy(**overrides)
        runner = AgentboxRunner("/bin/agentbox", policy, "/tmp/logs")
        return runner.command(
            "/repo", "agent/x", "/tmp/p.md", "refs/remotes/origin/main",
            effort=decision,
        )

    def test_the_pinned_model_ids_reach_agentbox(self):
        decision = effort_mod.resolve(issue(), self.policy, self.catalog)
        cmd = self.command_for(decision)
        self.assertIn("--model", cmd)
        self.assertIn(decision.implementer.model, cmd)
        self.assertIn("--review-model", cmd)
        self.assertIn(decision.reviewer.model, cmd)

    def test_the_tier_name_is_never_an_argument(self):
        decision = effort_mod.resolve(issue(), self.policy, self.catalog)
        cmd = self.command_for(decision)
        self.assertNotIn("standard", cmd)
        self.assertNotIn("S", cmd)

    def test_a_family_name_is_never_an_argument(self):
        decision = effort_mod.resolve(issue(), self.policy, self.catalog)
        cmd = self.command_for(decision)
        self.assertNotIn(decision.implementer.family, cmd)
        self.assertNotIn(decision.reviewer.family, cmd)

    def test_no_reviewer_is_named_when_the_policy_wants_no_review(self):
        decision = effort_mod.resolve(issue(), self.policy, self.catalog)
        cmd = self.command_for(decision, reviewPolicy="none")
        self.assertIn("none", cmd)
        self.assertNotIn("--review-model", cmd)

    def test_without_a_catalog_the_command_is_what_it_always_was(self):
        cmd = self.command_for(None)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("--review-model", cmd)


# ------------------------------------------------------------- the coordinator --


class TestTheCoordinator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = effort_mod.load(CATALOG_PATH)

    def build(self, github, runner, policy):
        return Coordinator(
            github, self.git, policy, runner, self.tmp.name,
            os.path.join(_ROOT, "bin", "scan-secrets"),
            emit=lambda line: None, dry_run=False, run_id="testrun",
            agent_identities=(fakes.AGENT_IDENTITY,),
            sleep=lambda _s: None,
            effort_catalog=self.catalog,
        )

    def run_issue(self, title="Add a helper", labels=("ready-for-agent",), script=None):
        github = fakes.FakeGitHub()
        github.add_issue(7, title=title, labels=tuple(labels))
        self.git = fakes.FakeGit()
        runner = fakes.FakeRunner(self.git, script=script)
        policy = fakes.make_policy(scanDiffForSecrets=False, requireCiChecks=False)
        coordinator = self.build(github, runner, policy)
        result = coordinator.process_issue(7)
        return result, runner

    def test_the_run_carries_the_tier_it_resolved(self):
        _, runner = self.run_issue()
        self.assertTrue(runner.calls)
        decision = runner.calls[0]["effort"]
        self.assertIsNotNone(decision)
        self.assertEqual(decision.id, "standard")

    def test_a_documentation_issue_runs_on_the_lightweight_tier(self):
        _, runner = self.run_issue(
            title="Fix a typo", labels=("ready-for-agent", "documentation")
        )
        self.assertEqual(runner.calls[0]["effort"].id, "lightweight")

    def test_the_decision_is_written_to_the_run_directory(self):
        self.run_issue()
        path = os.path.join(self.tmp.name, "runs", "testrun-i7", "effort.json")
        self.assertTrue(os.path.isfile(path), path)
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["issue"], 7)
        self.assertEqual(record["decisions"][0]["phase"], "implement")
        self.assertEqual(record["decisions"][0]["tier"], "standard")
        self.assertTrue(record["decisions"][0]["implementer"]["model"])

    def test_a_repair_runs_on_a_higher_tier_than_the_first_attempt(self):
        failing = {
            "summary": {
                "checksPassed": False,
                "failedChecks": [{"command": "pnpm test", "exitCode": 1, "tail": "boom"}],
                "fixRounds": 0,
                "review": {"skipped": True, "reason": "no credential"},
                "resultCommit": "sha-one",
            }
        }
        passing = {"checks_passed": True}
        _, runner = self.run_issue(script=[failing, passing])
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0]["effort"].id, "standard")
        self.assertEqual(runner.calls[1]["effort"].id, "hard")
        self.assertTrue(runner.calls[1]["continuation"])

    def test_the_repair_tier_is_recorded_beside_the_first(self):
        failing = {
            "summary": {
                "checksPassed": False,
                "failedChecks": [{"command": "pnpm test", "exitCode": 1, "tail": "boom"}],
                "fixRounds": 0,
                "review": {"skipped": True, "reason": "no credential"},
                "resultCommit": "sha-one",
            }
        }
        self.run_issue(script=[failing, {"checks_passed": True}])
        path = os.path.join(self.tmp.name, "runs", "testrun-i7", "effort.json")
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(
            [entry["phase"] for entry in record["decisions"]],
            ["implement", "repair-1"],
        )
        self.assertEqual(record["decisions"][1]["tier"], "hard")


# -------------------------------------------------------------- the display --


class TestTheDisplay(unittest.TestCase):
    def setUp(self):
        self.catalog = effort_mod.load(CATALOG_PATH)
        self.decision = effort_mod.resolve(issue(), fakes.make_policy(), self.catalog)

    def test_the_implementer_shows_its_marker_and_family(self):
        label = _agent_label({"agent": "claude"}, self.decision)
        self.assertEqual(label, f"(S) {self.decision.implementer.family}")

    def test_the_reviewer_shows_the_reviewer_family(self):
        label = _agent_label({"agent": "codex"}, self.decision)
        self.assertEqual(label, f"(S) {self.decision.reviewer.family}")

    def test_an_unknown_agent_falls_back_to_its_own_name(self):
        self.assertEqual(_agent_label({"agent": "other"}, self.decision), "Other")

    def test_without_a_decision_the_display_is_what_it_always_was(self):
        self.assertEqual(_agent_label({"agent": "claude"}), "Claude")


if __name__ == "__main__":
    unittest.main(verbosity=1)
