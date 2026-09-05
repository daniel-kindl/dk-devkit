"""The agentqueue command line.

    agentqueue drain  --repo PATH [options]   drain the backlog
    agentqueue plan   --repo PATH             the dry run, an alias of
                                              "drain --dry-run"
    agentqueue doctor --repo PATH             what is ready, what is missing
    agentqueue policy --repo PATH             the resolved policy and its source
    agentqueue init   --repo PATH             write a policy file to start from

Exit codes, stable, scripts may depend on them:

    0   the queue drained, or it is empty, or what is left is legitimately
        blocked
    1   a coordinator defect
    2   a usage error
    3   the policy is unusable
    4   a security or integrity failure stopped the queue
    5   the machine is not ready
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from typing import List, Optional

from . import VERSION, policy as policy_mod, report as report_mod
from .coordinator import Coordinator
from .ghapi import GitHub, GhTransport
from .gitops import Git, GitError
from .model import Outcome, Runnability
from .runner import AgentboxRunner

EXIT_OK = 0
EXIT_DEFECT = 1
EXIT_USAGE = 2
EXIT_POLICY = 3
EXIT_SECURITY = 4
EXIT_NOT_READY = 5


def _emit(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _repo_root(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _agent_identities(repo_root: str) -> List[str]:
    """The identity every agentbox commit carries.

    It is read from manifests/sandcastle.env, so the two tools cannot drift.
    An adopted branch whose commits carry another identity is not agentbox
    work, and it is not adopted.
    """
    manifest = os.path.join(repo_root, "manifests", "sandcastle.env")
    name = email = ""
    try:
        with open(manifest, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("AGENTBOX_GIT_NAME="):
                    name = line.split("=", 1)[1].strip()
                elif line.startswith("AGENTBOX_GIT_EMAIL="):
                    email = line.split("=", 1)[1].strip()
    except OSError:
        return []
    return [f"{name} <{email}>"] if name and email else []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentqueue",
        description="Drain a GitHub implementation backlog with unattended agents.",
    )
    parser.add_argument("--version", action="version", version=f"agentqueue {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--repo", required=True, help="the repository to work on")
        p.add_argument("--config", help="an explicit policy file")
        p.add_argument("--label", help="override the ready label")
        p.add_argument("--base", help="override the base branch")

    drain = sub.add_parser("drain", help="drain the backlog")
    common(drain)
    drain.add_argument("--max-parallel", type=int, help="issues at a time")
    drain.add_argument("--max-retries", type=int, help="repair attempts per issue")
    drain.add_argument("--merge-method", choices=("squash", "merge", "rebase"))
    drain.add_argument("--auto-merge", dest="auto_merge", action="store_true",
                       default=None, help="merge when every gate passes")
    drain.add_argument("--no-auto-merge", dest="auto_merge", action="store_false",
                       help="stop at a green pull request")
    drain.add_argument("--once", action="store_true",
                       help="process one wave, then stop")
    drain.add_argument("--dry-run", action="store_true",
                       help="print the plan and change nothing")

    plan = sub.add_parser("plan", help="print the plan and change nothing")
    common(plan)

    doctor = sub.add_parser("doctor", help="report what is ready")
    common(doctor)

    show = sub.add_parser("policy", help="print the resolved policy")
    common(show)
    show.add_argument("--json", action="store_true")

    init = sub.add_parser("init", help="write a policy file to start from")
    common(init)
    init.add_argument("--local", action="store_true",
                      help="write to ~/.config/agentqueue instead of the repository")
    init.add_argument("--force", action="store_true")
    return parser


def _load(args, install_root: str):
    repo_root = _repo_root(args.repo)
    git = Git(repo_root)
    if not git.is_repository():
        raise SystemExit_(EXIT_USAGE, f"not a Git working tree: {repo_root}")
    owner, name = git.remote_slug()
    default = os.path.join(install_root, "config", "agentqueue", "policy.default.json")
    pol = policy_mod.load(repo_root, default, owner, name, args.config)
    if getattr(args, "label", None):
        pol.issueLabel = args.label
    if getattr(args, "base", None):
        pol.baseBranch = args.base
    for attr, field in (
        ("max_parallel", "maxParallel"),
        ("max_retries", "maxRetries"),
        ("merge_method", "mergeMethod"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            setattr(pol, field, value)
    if getattr(args, "auto_merge", None) is not None:
        pol.autoMerge = args.auto_merge
    pol.validate()
    return repo_root, git, owner, name, pol


class SystemExit_(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _state_dir() -> str:
    base = os.environ.get("AGENTQUEUE_STATE_DIR")
    if base:
        return base
    return os.path.join(
        os.path.expanduser("~"), ".local", "share", "agentqueue"
    )


def cmd_policy(args, install_root: str) -> int:
    _, _, owner, name, pol = _load(args, install_root)
    if args.json:
        print(json.dumps(pol.as_dict(), indent=2, sort_keys=True))
        return EXIT_OK
    print(f"repository   {owner}/{name}")
    print("sources      " + ("\n             ".join(pol.sources) or "(built-in only)"))
    for key, value in sorted(pol.as_dict().items()):
        if key == "sources":
            continue
        print(f"  {key:<28} {value}")
    return EXIT_OK


def cmd_doctor(args, install_root: str) -> int:
    repo_root, git, owner, name, pol = _load(args, install_root)
    rc = EXIT_OK
    print("agentqueue doctor\n")
    print(f"  repository         {repo_root}")
    print(f"  GitHub             {owner}/{name}")
    print(f"  base branch        {pol.baseBranch}")
    print(f"  policy sources     {', '.join(pol.sources) or '(built-in only)'}")

    transport = GhTransport()
    if not transport.available():
        print("  gh                 NOT FOUND (agentqueue runs inside web-dev)")
        rc = EXIT_NOT_READY
    else:
        code, out, _ = transport.run(["auth", "status"])
        print(f"  gh                 present, auth {'ok' if code == 0 else 'MISSING'}")
        if code != 0:
            rc = EXIT_NOT_READY

    agentbox = os.path.join(install_root, "bin", "agentbox")
    print(f"  agentbox           {agentbox}"
          f"{'' if os.access(agentbox, os.X_OK) else '  NOT EXECUTABLE'}")
    if not os.access(agentbox, os.X_OK):
        rc = EXIT_NOT_READY

    sock = os.environ.get("SSH_AUTH_SOCK", "")
    print(f"  ssh-agent          {sock or 'NOT FORWARDED (git push will fail)'}")
    if not sock:
        rc = EXIT_NOT_READY

    base = git.rev_parse(f"refs/remotes/origin/{pol.baseBranch}")
    print(f"  origin/{pol.baseBranch:<12}{base[:12] if base else 'MISSING'}")
    if not base:
        rc = EXIT_NOT_READY
    busy = git.operation_in_progress()
    print(f"  repository state   {busy or 'idle'}")
    if busy:
        rc = EXIT_NOT_READY

    print(f"  autoMerge          {pol.autoMerge}")
    print(f"  reviewPolicy       {pol.reviewPolicy}"
          f"  (merge without review: {pol.merge_is_permitted_without_review()})")
    print(f"  checks             {', '.join(pol.checks) or '(none)'}")
    print("\nagentqueue: " + ("ready" if rc == EXIT_OK else "not ready"))
    return rc


def cmd_init(args, install_root: str) -> int:
    repo_root, _, owner, name, _ = _load(args, install_root)
    template = {
        "version": 1,
        "baseBranch": "main",
        "issueLabel": "ready-for-agent",
        "checks": ["pnpm install --frozen-lockfile", "pnpm check"],
        "requiredChecks": [],
        "reviewPolicy": "optional",
        "mergeWithoutReview": False,
        "autoMerge": False,
        "mergeMethod": "squash",
        "maxParallel": 1,
        "maxRetries": 2,
    }
    if args.local:
        target = os.path.join(
            os.path.expanduser("~"), ".config", "agentqueue", "repos",
            policy_mod.repo_slug(owner, name) + ".json",
        )
    else:
        target = os.path.join(repo_root, ".agentqueue.json")
    if os.path.exists(target) and not args.force:
        print(f"agentqueue: {target} exists already. Pass --force to replace it.")
        return EXIT_USAGE
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(template, handle, indent=2)
        handle.write("\n")
    print(f"agentqueue: wrote {target}")
    print("Review it, then turn autoMerge on when the policy is what you want.")
    return EXIT_OK


def cmd_drain(args, install_root: str, dry_run: bool) -> int:
    repo_root, git, owner, name, pol = _load(args, install_root)
    state_dir = _state_dir()
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    github = GitHub(owner, name, dry_run=dry_run)
    git.dry_run = dry_run

    runner = AgentboxRunner(
        os.path.join(install_root, "bin", "agentbox"),
        pol,
        os.path.join(state_dir, "runs", run_id),
        dry_run=dry_run,
        emit=_emit,
    )
    coordinator = Coordinator(
        github, git, pol, runner, state_dir,
        os.path.join(install_root, "bin", "scan-secrets"),
        emit=_emit, dry_run=dry_run, run_id=run_id,
        agent_identities=_agent_identities(install_root),
    )

    print(f"agentqueue {VERSION}")
    print(f"  repository   {owner}/{name}  ({repo_root})")
    print(f"  base         {pol.baseBranch}")
    print(f"  label        {pol.issueLabel}")
    print(f"  autoMerge    {pol.autoMerge}   mergeMethod {pol.mergeMethod}")
    print(f"  maxParallel  {pol.maxParallel}   maxRetries {pol.maxRetries}")
    print(f"  run id       {run_id}")
    if dry_run:
        print("  DRY RUN - nothing is changed, on GitHub or on disk\n")
        verdicts = coordinator.scan()
        cycles = list(getattr(coordinator.scheduler, "cycles", []))
        for line in report_mod.render_plan(verdicts, cycles):
            print(line)
        print("\n  what a real run would do next:")
        order = [v.issue for v in verdicts if v.runnability is Runnability.RUNNABLE]
        if not order:
            print("    nothing; the queue is empty or every issue is blocked")
        for number in order[: pol.maxParallel]:
            branch, note = coordinator._branch_for(github.get_issue(number))
            print(f"    #{number} -> {branch or 'NO USABLE BRANCH'}"
                  + (f"  ({note})" if note else ""))
        print("\n  mutations attempted: "
              f"{len(github.mutations) + len(git.mutations)} (must be 0)")
        return EXIT_OK if not github.mutations and not git.mutations else EXIT_DEFECT

    print()
    git.fetch()
    report = coordinator.drain(once=args.once)
    for line in report_mod.render_summary(report, pol):
        print(line)
    if report.stopped_for_security:
        return EXIT_SECURITY
    return EXIT_OK


def main(argv: Optional[List[str]] = None, install_root: str = "") -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    install_root = install_root or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    try:
        if args.command == "policy":
            return cmd_policy(args, install_root)
        if args.command == "doctor":
            return cmd_doctor(args, install_root)
        if args.command == "init":
            return cmd_init(args, install_root)
        if args.command == "plan":
            args.once = False
            return cmd_drain(args, install_root, dry_run=True)
        if args.command == "drain":
            return cmd_drain(args, install_root, dry_run=bool(args.dry_run))
    except policy_mod.PolicyError as exc:
        sys.stderr.write(f"agentqueue: {exc}\n")
        return EXIT_POLICY
    except SystemExit_ as exc:
        sys.stderr.write(f"agentqueue: {exc.message}\n")
        return exc.code
    except GitError as exc:
        sys.stderr.write(f"agentqueue: {exc}\n")
        return EXIT_USAGE
    except KeyboardInterrupt:
        sys.stderr.write("agentqueue: interrupted\n")
        return EXIT_DEFECT
    return EXIT_USAGE
