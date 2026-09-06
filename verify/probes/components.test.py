#!/usr/bin/env python3
"""Deterministic tests for the toolkit component installer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bin" / "toolkit-install"
loader = SourceFileLoader("toolkit_install", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec
toolkit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toolkit
loader.exec_module(toolkit)


def manifest(identifier, **overrides):
    document = {
        "version": 1,
        "id": identifier,
        "name": identifier,
        "kind": "tool",
        "group": "Core tools",
        "summary": "a component",
        "requires": [],
        "capabilities": [],
        "unattended": True,
        "install": ["true"],
        "doctor": None,
        "verify": None,
        "manual": [],
        "state": {"public": [], "local": []},
    }
    document.update(overrides)
    return document


def catalogue(*documents):
    """Write component manifests into a throwaway directory and load them."""
    directory = Path(tempfile.mkdtemp())
    for document in documents:
        component = directory / document["id"]
        component.mkdir()
        (component / "component.json").write_text(json.dumps(document), encoding="utf-8")
    return toolkit.load_components(directory)


def host(commands=(), executables=(), system="Linux", in_container=False,
         os_release=None, wsl=False):
    return toolkit.Host(
        which=lambda name: f"/usr/bin/{name}" if name in commands else None,
        is_executable=lambda path: path in executables,
        system=system,
        machine="x86_64",
        in_container=in_container,
        os_release=os_release or {},
        wsl=wsl,
    )


def plan_for(components, selection, present=frozenset(), ready=(), force=False):
    reasons, order = toolkit.closure(components, selection)
    return toolkit.build_plan(
        components, reasons, order, frozenset(present), ROOT, force=force,
        doctor=lambda component, root: component.id in ready,
    )


def ids(steps):
    return [step.component.id for step in steps]


# ------------------------------------------------------------- the contract --


class ManifestCase(unittest.TestCase):
    def test_a_component_round_trips(self):
        components = catalogue(manifest("alpha"))
        self.assertEqual(list(components), ["alpha"])
        self.assertEqual(components["alpha"].install, ("true",))

    def test_version_must_be_one(self):
        with self.assertRaises(toolkit.ConfigError):
            catalogue(manifest("alpha", version=2))

    def test_kind_must_be_known(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "kind must be one of"):
            catalogue(manifest("alpha", kind="widget"))

    def test_unattended_must_be_declared(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "unattended"):
            catalogue(manifest("alpha", unattended="yes"))

    def test_a_directory_name_must_match_the_declared_id(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "alpha").mkdir()
        (directory / "alpha" / "component.json").write_text(
            json.dumps(manifest("beta")), encoding="utf-8"
        )
        with self.assertRaisesRegex(toolkit.ConfigError, "but lives in"):
            toolkit.load_components(directory)

    def test_a_dependency_must_be_a_component(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "not a component"):
            catalogue(manifest("alpha", requires=["ghost"]))

    def test_a_component_must_not_require_itself(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "require itself"):
            catalogue(manifest("alpha", requires=["alpha"]))

    def test_an_empty_command_is_rejected(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "empty command"):
            catalogue(manifest("alpha", install=[]))

    def test_a_capability_must_be_defined(self):
        components = catalogue(manifest("alpha", capabilities=["quantum"]))
        capabilities = toolkit.load_capabilities(ROOT / "manifests" / "capabilities.json")
        with self.assertRaisesRegex(toolkit.ConfigError, "quantum"):
            toolkit.check_capability_references(components, capabilities)


# ---------------------------------------------------------------- probes --


class CapabilityCase(unittest.TestCase):
    def setUp(self):
        self.capabilities = toolkit.load_capabilities(
            ROOT / "manifests" / "capabilities.json"
        )

    def test_shipped_capability_manifest_is_valid(self):
        self.assertIn("container-runtime", self.capabilities)
        self.assertTrue(all(c.summary for c in self.capabilities.values()))

    def test_a_command_probe_follows_the_path(self):
        present = toolkit.detect_capabilities(self.capabilities, host(commands={"git"}))
        self.assertIn("git", present)
        self.assertNotIn("gh", present)

    def test_the_host_capability_is_absent_inside_a_container(self):
        outside = toolkit.detect_capabilities(self.capabilities, host())
        inside = toolkit.detect_capabilities(self.capabilities, host(in_container=True))
        self.assertIn("host", outside)
        self.assertNotIn("host", inside)

    def test_any_matches_either_runtime(self):
        podman = toolkit.detect_capabilities(self.capabilities, host(commands={"podman"}))
        docker = toolkit.detect_capabilities(self.capabilities, host(commands={"docker"}))
        neither = toolkit.detect_capabilities(self.capabilities, host())
        self.assertIn("container-runtime", podman)
        self.assertIn("container-runtime", docker)
        self.assertNotIn("container-runtime", neither)

    def test_an_executable_probe_needs_the_path(self):
        brewed = toolkit.detect_capabilities(
            self.capabilities, host(executables={"/home/linuxbrew/.linuxbrew/bin/brew"})
        )
        self.assertIn("homebrew", brewed)

    def test_uname_gates_the_platform(self):
        elsewhere = toolkit.detect_capabilities(self.capabilities, host(system="Darwin"))
        self.assertNotIn("linux", elsewhere)

    def test_a_malformed_probe_is_rejected(self):
        with self.assertRaisesRegex(toolkit.ConfigError, "probe.kind"):
            toolkit._check_probe({"kind": "vibes", "value": "x"}, "probe")


# ------------------------------------------------------------- resolution --


class ClosureCase(unittest.TestCase):
    def test_an_unknown_component_is_named(self):
        components = catalogue(manifest("alpha"))
        with self.assertRaisesRegex(toolkit.ResolveError, "unknown component: ghost"):
            toolkit.closure(components, ["ghost"])

    def test_a_dependency_joins_the_closure_with_its_reason(self):
        components = catalogue(manifest("alpha", requires=["beta"]), manifest("beta"))
        reasons, order = toolkit.closure(components, ["alpha"])
        self.assertEqual(reasons["alpha"], "selected")
        self.assertEqual(reasons["beta"], "required by alpha")
        self.assertEqual(order, ("beta", "alpha"))

    def test_a_transitive_dependency_is_installed_because_it_is_declared(self):
        components = catalogue(
            manifest("alpha", requires=["beta"]),
            manifest("beta", requires=["gamma"]),
            manifest("gamma"),
        )
        reasons, order = toolkit.closure(components, ["alpha"])
        self.assertEqual(order, ("gamma", "beta", "alpha"))
        self.assertEqual(reasons["gamma"], "required by beta")

    def test_nothing_unrelated_joins_the_closure(self):
        components = catalogue(manifest("alpha"), manifest("desktop"))
        _, order = toolkit.closure(components, ["alpha"])
        self.assertEqual(order, ("alpha",))

    def test_the_order_does_not_depend_on_the_selection_order(self):
        components = catalogue(
            manifest("alpha", requires=["shared"]),
            manifest("beta", requires=["shared"]),
            manifest("shared"),
        )
        first = toolkit.closure(components, ["alpha", "beta"])[1]
        second = toolkit.closure(components, ["beta", "alpha"])[1]
        self.assertEqual(first, second)
        self.assertEqual(first, ("shared", "alpha", "beta"))

    def test_a_cycle_is_rejected(self):
        components = catalogue(
            manifest("alpha", requires=["beta"]),
            manifest("beta", requires=["alpha"]),
        )
        with self.assertRaisesRegex(toolkit.ResolveError, "dependency cycle"):
            toolkit.closure(components, ["alpha"])

    def test_a_longer_cycle_is_rejected(self):
        components = catalogue(
            manifest("alpha", requires=["beta"]),
            manifest("beta", requires=["gamma"]),
            manifest("gamma", requires=["alpha"]),
        )
        with self.assertRaisesRegex(toolkit.ResolveError, "dependency cycle"):
            toolkit.closure(components, ["gamma"])


# ---------------------------------------------------------------- planning --


class PlanCase(unittest.TestCase):
    def test_a_ready_component_is_not_installed_again(self):
        components = catalogue(manifest("alpha", doctor=["true"]))
        plan = plan_for(components, ["alpha"], ready={"alpha"})
        self.assertEqual(ids(plan.of(toolkit.READY)), ["alpha"])
        self.assertEqual(plan.of(toolkit.INSTALL), ())

    def test_force_installs_a_ready_component_again(self):
        components = catalogue(manifest("alpha", doctor=["true"]))
        plan = plan_for(components, ["alpha"], ready={"alpha"}, force=True)
        self.assertEqual(ids(plan.of(toolkit.INSTALL)), ["alpha"])

    def test_a_missing_capability_blocks_the_component(self):
        components = catalogue(manifest("alpha", capabilities=["podman"]))
        plan = plan_for(components, ["alpha"])
        self.assertEqual(ids(plan.blocked), ["alpha"])
        self.assertIn("missing capability: podman", plan.blocked[0].detail)

    def test_a_blocked_dependency_blocks_its_dependent(self):
        components = catalogue(
            manifest("alpha", requires=["beta"]), manifest("beta", capabilities=["podman"])
        )
        plan = plan_for(components, ["alpha"])
        self.assertEqual(ids(plan.blocked), ["beta", "alpha"])
        self.assertIn("blocked by: beta", plan.blocked[1].detail)

    def test_a_component_without_an_installer_needs_the_platform_to_supply_it(self):
        components = catalogue(manifest("alpha", install=None, doctor=["false"]))
        plan = plan_for(components, ["alpha"])
        self.assertIn("no installer", plan.blocked[0].detail)

    def test_a_profile_installs_nothing_of_its_own(self):
        components = catalogue(
            manifest("profile", kind="profile", install=None, requires=["alpha"]),
            manifest("alpha"),
        )
        plan = plan_for(components, ["profile"])
        self.assertEqual(ids(plan.of(toolkit.COMPOSITION)), ["profile"])
        self.assertEqual(ids(plan.of(toolkit.INSTALL)), ["alpha"])

    def test_a_blocked_component_does_not_report_its_manual_steps(self):
        components = catalogue(
            manifest("alpha", capabilities=["podman"], manual=["sign in somewhere"])
        )
        self.assertEqual(plan_for(components, ["alpha"]).manual, ())

    def test_manual_steps_are_reported_once_each(self):
        components = catalogue(
            manifest("alpha", manual=["same step"]), manifest("beta", manual=["same step"])
        )
        self.assertEqual(plan_for(components, ["alpha", "beta"]).manual, ("same step",))

    def test_the_plan_says_why_a_dependency_is_there(self):
        components = catalogue(manifest("alpha", requires=["beta"]), manifest("beta"))
        rendered = toolkit.render_plan(plan_for(components, ["alpha"]))
        self.assertIn("required by alpha", rendered)


# -------------------------------------------------------------- execution --


class ExecutionCase(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def runner(self, command, root, capture=False):
        self.calls.append(tuple(command))
        return subprocess.CompletedProcess(list(command), 0)

    def failing(self, command, root, capture=False):
        self.calls.append(tuple(command))
        return subprocess.CompletedProcess(list(command), 3)

    def test_components_install_in_dependency_order(self):
        components = catalogue(
            manifest("alpha", requires=["beta"], install=["install-alpha"]),
            manifest("beta", install=["install-beta"]),
        )
        toolkit.execute(plan_for(components, ["alpha"]), ROOT, runner=self.runner)
        self.assertEqual(self.calls, [("install-beta",), ("install-alpha",)])

    def test_a_failing_component_is_named_and_stops_the_run(self):
        components = catalogue(
            manifest("alpha", requires=["beta"], install=["install-alpha"]),
            manifest("beta", install=["install-beta"]),
        )
        failure = toolkit.execute(plan_for(components, ["alpha"]), ROOT, runner=self.failing)
        self.assertEqual(failure.component.id, "beta")
        self.assertEqual(failure.detail, "exit 3")
        self.assertEqual(self.calls, [("install-beta",)])

    def test_a_ready_component_runs_no_install_command(self):
        components = catalogue(manifest("alpha", doctor=["true"], install=["install-alpha"]))
        toolkit.execute(plan_for(components, ["alpha"], ready={"alpha"}), ROOT, runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_verification_targets_only_the_selected_graph(self):
        components = catalogue(
            manifest("alpha", verify=["verify-alpha"]),
            manifest("unrelated", verify=["verify-unrelated"]),
        )
        toolkit.verify(plan_for(components, ["alpha"]), ROOT, runner=self.runner)
        self.assertEqual(self.calls, [("verify-alpha",)])

    def test_a_blocked_component_is_not_verified(self):
        components = catalogue(
            manifest("alpha", capabilities=["podman"], verify=["verify-alpha"])
        )
        toolkit.verify(plan_for(components, ["alpha"]), ROOT, runner=self.runner)
        self.assertEqual(self.calls, [])

    def test_a_failing_verification_is_reported(self):
        components = catalogue(manifest("alpha", verify=["verify-alpha"]))
        failed = toolkit.verify(plan_for(components, ["alpha"]), ROOT, runner=self.failing)
        self.assertEqual(ids(failed), ["alpha"])


# ------------------------------------------------------------ the real tree --


class ShippedCatalogueCase(unittest.TestCase):
    def setUp(self):
        self.components = toolkit.load_components(ROOT / "components")
        self.capabilities = toolkit.load_capabilities(
            ROOT / "manifests" / "capabilities.json"
        )

    def test_every_component_loads(self):
        self.assertIn("devbox", self.components)
        toolkit.check_capability_references(self.components, self.capabilities)

    def test_no_component_graph_has_a_cycle(self):
        toolkit.closure(self.components, sorted(self.components))

    def test_every_declared_command_exists_and_is_executable(self):
        for component in self.components.values():
            for command in (component.install, component.doctor, component.verify):
                if command is None:
                    continue
                candidate = ROOT / command[0]
                if not candidate.exists():
                    continue
                self.assertTrue(
                    candidate.is_file() and candidate.stat().st_mode & 0o111,
                    f"{component.id}: {command[0]} is not executable",
                )

    def test_the_daniel_profile_composes_every_other_component(self):
        _, order = toolkit.closure(self.components, ["daniel"])
        self.assertEqual(set(order), set(self.components))
        self.assertEqual(order[-1], "daniel")
        self.assertIsNone(self.components["daniel"].install)

    def test_a_reusable_tool_pulls_in_no_workstation_extras(self):
        _, order = toolkit.closure(self.components, ["agentbox"])
        self.assertEqual(order, ("agentbox",))

    def test_an_environment_pulls_in_its_runtime_and_the_router_only(self):
        _, order = toolkit.closure(self.components, ["web-dev"])
        self.assertEqual(set(order), {"devbox", "distrobox", "web-dev"})

    def test_every_named_profile_exists(self):
        self.assertEqual(
            toolkit.profile_ids(self.components),
            ("agent-dev", "daniel", "developer", "minimal"),
        )

    def test_a_profile_installs_nothing_of_its_own(self):
        for name in toolkit.profile_ids(self.components):
            self.assertIsNone(self.components[name].install, name)
            self.assertIsNone(self.components[name].doctor, name)

    def test_each_profile_contains_the_smaller_one(self):
        expansions = [
            set(toolkit.closure(self.components, [name])[1])
            for name in ("minimal", "developer", "agent-dev", "daniel")
        ]
        for smaller, larger in zip(expansions, expansions[1:]):
            self.assertTrue(smaller < larger, f"{smaller} is not inside {larger}")

    def test_a_profile_is_never_a_dependency_of_a_reusable_component(self):
        for component in self.components.values():
            if component.kind == "profile":
                continue
            for dependency in component.requires:
                self.assertNotEqual(
                    self.components[dependency].kind, "profile",
                    f"{component.id} depends on the {dependency} profile",
                )

    def test_a_small_profile_pulls_in_no_workstation_extras(self):
        _, order = toolkit.closure(self.components, ["minimal"])
        self.assertEqual(set(order), {"minimal", "devbox", "agent-home"})

    def test_no_component_declares_a_credential_path_as_public_state(self):
        for component in self.components.values():
            for entry in component.public_state:
                self.assertNotIn("secrets", entry, f"{component.id}: {entry}")
                self.assertNotIn("auth", entry, f"{component.id}: {entry}")


# --------------------------------------------------------------- profiles --


def picker(*documents):
    return toolkit.picker_entries(catalogue(*documents))


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.components = catalogue(
            manifest("tiny", kind="profile", requires=["alpha"], install=None),
            manifest("alpha"),
        )

    def test_a_profile_expands_to_the_components_it_composes(self):
        _, order = toolkit.closure(self.components, ["tiny"])
        self.assertEqual(order, ("alpha", "tiny"))

    def test_the_profiles_are_listed_in_one_order(self):
        self.assertEqual(toolkit.profile_ids(self.components), ("tiny",))

    def test_an_unknown_profile_names_the_ones_that_exist(self):
        with self.assertRaisesRegex(toolkit.ResolveError, "unknown profile: ghost"):
            toolkit.resolve_profiles(self.components, ["ghost"])

    def test_a_component_is_not_a_profile(self):
        with self.assertRaisesRegex(toolkit.ResolveError, "not a profile"):
            toolkit.resolve_profiles(self.components, ["alpha"])

    def test_a_repeated_profile_is_resolved_once(self):
        self.assertEqual(
            toolkit.resolve_profiles(self.components, ["tiny", "tiny"]), ("tiny",)
        )


# ----------------------------------------------------------------- picker --


class PickerCase(unittest.TestCase):
    def setUp(self):
        self.entries = picker(
            manifest("alpha", group="Core tools"),
            manifest("beta", group="Core tools", capabilities=["flatpak"]),
            manifest("tiny", group="Profiles", kind="profile", install=None),
        )

    def test_the_number_of_a_component_comes_from_group_then_identifier(self):
        self.assertEqual([item.id for item in self.entries], ["alpha", "beta", "tiny"])

    def test_a_number_toggles_the_component_it_names(self):
        action, selection, _ = toolkit.picker_command(self.entries, (), "2")
        self.assertEqual((action, selection), (toolkit.TOGGLE, ("beta",)))

    def test_the_same_number_toggles_the_component_off_again(self):
        _, selection, _ = toolkit.picker_command(self.entries, ("beta",), "2")
        self.assertEqual(selection, ())

    def test_an_identifier_selects_the_same_component_as_its_number(self):
        by_name = toolkit.picker_command(self.entries, (), "tiny")[1]
        by_number = toolkit.picker_command(self.entries, (), "3")[1]
        self.assertEqual(by_name, by_number)

    def test_several_choices_are_accepted_on_one_line(self):
        _, selection, _ = toolkit.picker_command(self.entries, (), "1, 2 tiny")
        self.assertEqual(selection, ("alpha", "beta", "tiny"))

    def test_the_selection_does_not_depend_on_the_order_it_was_typed(self):
        first = toolkit.picker_command(self.entries, (), "1 3")[1]
        second = toolkit.picker_command(self.entries, (), "3 1")[1]
        self.assertEqual(first, second)

    def test_an_unknown_word_changes_nothing_and_says_so(self):
        action, selection, message = toolkit.picker_command(
            self.entries, ("alpha",), "1 ghost"
        )
        self.assertEqual((action, selection), (toolkit.TOGGLE, ("alpha",)))
        self.assertIn("unknown choice: ghost", message)

    def test_a_number_outside_the_list_changes_nothing(self):
        _, selection, message = toolkit.picker_command(self.entries, ("alpha",), "9")
        self.assertEqual(selection, ("alpha",))
        self.assertIn("no such number: 9", message)

    def test_none_clears_the_selection(self):
        _, selection, _ = toolkit.picker_command(self.entries, ("alpha", "beta"), "none")
        self.assertEqual(selection, ())

    def test_an_empty_line_confirms_the_selection(self):
        action, selection, _ = toolkit.picker_command(self.entries, ("alpha",), "")
        self.assertEqual((action, selection), (toolkit.CONFIRM, ("alpha",)))

    def test_an_empty_selection_cannot_be_confirmed(self):
        action, _, message = toolkit.picker_command(self.entries, (), "")
        self.assertEqual(action, toolkit.TOGGLE)
        self.assertIn("nothing is selected", message)

    def test_q_cancels(self):
        self.assertEqual(
            toolkit.picker_command(self.entries, ("alpha",), "q")[0], toolkit.CANCEL
        )

    def test_the_picker_marks_the_selection_and_the_missing_capability(self):
        text = toolkit.render_picker(self.entries, ("alpha",), frozenset())
        self.assertIn("[x]", text)
        self.assertIn("!", text)
        self.assertIn("Core tools", text)
        self.assertIn("Profiles", text)

    def test_a_long_summary_stays_on_one_line(self):
        entries = picker(manifest("alpha", summary="w" * 200))
        for line in toolkit.render_picker(entries, (), frozenset()).splitlines():
            self.assertLessEqual(len(line), 100)

    def test_the_picker_returns_what_the_human_confirmed(self):
        answers = iter(["2", ""])
        chosen = toolkit.run_picker(
            self.entries, frozenset(), read=lambda _: next(answers),
            write=lambda _text="": None,
        )
        self.assertEqual(chosen, ("beta",))

    def test_the_picker_returns_nothing_when_the_human_cancels(self):
        answers = iter(["1", "q"])
        self.assertIsNone(toolkit.run_picker(
            self.entries, frozenset(), read=lambda _: next(answers),
            write=lambda _text="": None,
        ))

    def test_a_closed_input_cancels_the_picker(self):
        def closed(_prompt):
            raise EOFError

        self.assertIsNone(toolkit.run_picker(
            self.entries, frozenset(), read=closed, write=lambda _text="": None,
        ))

    def test_help_explains_the_choices_and_keeps_the_selection(self):
        answers = iter(["1", "?", ""])
        written = []
        chosen = toolkit.run_picker(
            self.entries, frozenset(), read=lambda _: next(answers),
            write=written.append,
        )
        self.assertEqual(chosen, ("alpha",))
        self.assertTrue(any("toggle" in line for line in written))

    def test_only_an_explicit_yes_confirms_the_plan(self):
        self.assertTrue(toolkit.confirm("go?", read=lambda _: "y"))
        self.assertTrue(toolkit.confirm("go?", read=lambda _: "YES"))
        self.assertFalse(toolkit.confirm("go?", read=lambda _: ""))
        self.assertFalse(toolkit.confirm("go?", read=lambda _: "n"))

    def test_a_closed_input_does_not_confirm_the_plan(self):
        def closed(_prompt):
            raise EOFError

        self.assertFalse(toolkit.confirm("go?", read=closed))


# --------------------------------------------------------------------- CLI --


class CommandLineCase(unittest.TestCase):
    def run_installer(self, *args, timeout=120):
        # stdin is closed, so a run that tried to ask a question would fail
        # here instead of blocking a machine that cannot answer it.
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
            stdin=subprocess.DEVNULL, timeout=timeout,
        )

    def test_list_changes_nothing_and_succeeds(self):
        result = self.run_installer("--list")
        self.assertEqual(result.returncode, toolkit.EXIT_OK)
        self.assertIn("devbox", result.stdout)

    def test_no_selection_is_a_usage_error(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, toolkit.EXIT_USAGE)
        self.assertIn("--list", result.stderr)

    def test_an_unknown_component_exits_with_the_resolve_code(self):
        result = self.run_installer("--components", "ghost")
        self.assertEqual(result.returncode, toolkit.EXIT_RESOLVE)
        self.assertIn("unknown component: ghost", result.stderr)

    def test_dry_run_prints_the_plan_and_exits_zero(self):
        result = self.run_installer("--dry-run", "--components", "daniel")
        self.assertEqual(result.returncode, toolkit.EXIT_OK)
        self.assertIn("daniel", result.stdout)

    def test_no_selection_names_the_profiles_and_does_not_wait(self):
        result = self.run_installer(timeout=30)
        self.assertEqual(result.returncode, toolkit.EXIT_USAGE)
        self.assertIn("--profile", result.stderr)
        self.assertIn("developer", result.stderr)

    def test_a_profile_resolves_the_same_closure_a_component_would(self):
        by_profile = self.run_installer("--dry-run", "--profile", "minimal")
        by_component = self.run_installer("--dry-run", "--components", "minimal")
        self.assertEqual(by_profile.returncode, toolkit.EXIT_OK)
        self.assertEqual(by_profile.stdout, by_component.stdout)

    def test_an_unknown_profile_exits_with_the_resolve_code(self):
        result = self.run_installer("--profile", "ghost")
        self.assertEqual(result.returncode, toolkit.EXIT_RESOLVE)
        self.assertIn("unknown profile: ghost", result.stderr)

    def test_a_component_passed_as_a_profile_is_refused(self):
        result = self.run_installer("--profile", "devbox")
        self.assertEqual(result.returncode, toolkit.EXIT_RESOLVE)
        self.assertIn("not a profile", result.stderr)

    def test_a_profile_and_a_component_select_both(self):
        result = self.run_installer(
            "--dry-run", "--profile", "minimal", "--components", "repo-labels"
        )
        self.assertEqual(result.returncode, toolkit.EXIT_OK)
        self.assertIn("repo-labels", result.stdout)
        self.assertIn("minimal", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
