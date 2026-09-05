// selftest.mjs - prove the sandbox lifecycle without calling an agent.
//
// It runs inside the agent-runner container. It exercises every step of the
// agentbox lifecycle except the agent invocation itself, so it needs no model
// credential and costs nothing:
//
//   create the isolated branch and worktree
//   -> create the Podman sandbox
//   -> prove no key material and no Podman socket reached the sandbox
//   -> prove the shared policy and skills are readable inside the sandbox
//   -> run the deterministic checks
//   -> prove the checked-out branch did not move
//   -> destroy the sandbox and remove the temporary branch
//
// bin/agentbox selftest drives it.

import { createSandbox } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { execFileSync } from "node:child_process";

const log = (m) => process.stdout.write(`[selftest] ${m}\n`);
const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();

const cfg = JSON.parse(process.env.AGENTBOX_CONFIG ?? "{}");
if (!cfg.repo) {
  process.stderr.write("[selftest] error: AGENTBOX_CONFIG has no repo\n");
  process.exit(1);
}

const branch = cfg.branch ?? `agent/selftest-${Date.now()}`;
const headBefore = git(cfg.repo, ["rev-parse", "HEAD"]);
const branchBefore = git(cfg.repo, ["rev-parse", "--abbrev-ref", "HEAD"]);

log(`repository       ${cfg.repo}`);
log(`checked out      ${branchBefore} @ ${headBefore.slice(0, 12)}`);
log(`sandbox branch   ${branch}`);
log(`sandbox image    ${cfg.sandboxImage}`);

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `  (${detail})`}`);
};

// Each probe prints "clean" when the sandbox is in the state it must be in.
const PROBES = [
  ["no ~/.ssh directory in the sandbox",
   "test ! -e ~/.ssh && echo clean || echo LEAK"],
  ["no private key material in the sandbox home",
   "if find ~ -maxdepth 4 \\( -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'id_ecdsa*' -o -name 'id_dsa*' \\) ! -name '*.pub' -print -quit 2>/dev/null | grep -q .; then echo LEAK; else echo clean; fi"],
  ["no ssh-agent socket forwarded into the sandbox",
   'test -z "$SSH_AUTH_SOCK" && echo clean || echo LEAK'],
  ["no Podman socket reachable from the sandbox",
   "test ! -e /run/user/1000/podman/podman.sock && echo clean || echo LEAK"],
  ["no credential file from the host home",
   "test ! -e ~/.claude/.credentials.json && test ! -e ~/.codex/auth.json && echo clean || echo LEAK"],
  ["the shared AGENTS.md policy is readable",
   "head -c 1 ~/.claude/CLAUDE.md >/dev/null 2>&1 && echo clean || echo MISSING"],
  ["the shared skill store is readable",
   "test -d ~/.claude/skills && echo clean || echo MISSING"],
  ["the sandbox is not privileged",
   "if capsh --print 2>/dev/null | grep -q 'cap_sys_admin'; then echo LEAK; else echo clean; fi"],
  ["the repository worktree is mounted and is a git worktree",
   "git rev-parse --is-inside-work-tree >/dev/null 2>&1 && echo clean || echo MISSING"],
];

let sandbox;
let exitCode = 0;

try {
  log("creating the sandbox");
  sandbox = await createSandbox({
    branch,
    cwd: cfg.repo,
    sandbox: podman({
      imageName: cfg.sandboxImage,
      mounts: cfg.mounts ?? [],
      selinuxLabel: "z",
      userns: "keep-id",
      containerUid: 1000,
      containerGid: 1000,
    }),
  });
  log(`worktree         ${sandbox.worktreePath}`);

  log("isolation probes");
  for (const [name, cmd] of PROBES) {
    const r = await sandbox.exec(cmd);
    const out = `${r.stdout}${r.stderr}`.trim().split("\n").pop() ?? "";
    record(name, r.exitCode === 0 && out === "clean", out);
  }

  log("the sandbox agent CLIs are present");
  for (const bin of ["claude", "codex", "git", "gh"]) {
    const r = await sandbox.exec(`command -v ${bin}`);
    record(`${bin} is on PATH in the sandbox`, r.exitCode === 0, r.stdout.trim());
  }

  log("deterministic checks");
  for (const cmd of cfg.checks ?? []) {
    const r = await sandbox.exec(cmd);
    record(`check: ${cmd}`, r.exitCode === 0, `exit ${r.exitCode}`);
  }

  // Writing inside the sandbox must not reach the checked-out branch.
  await sandbox.exec("printf 'selftest\\n' > SELFTEST_MARKER.txt");
  const headDuring = git(cfg.repo, ["rev-parse", "HEAD"]);
  record("the checked-out branch does not move while the sandbox runs",
    headDuring === headBefore, `${headDuring.slice(0, 12)} vs ${headBefore.slice(0, 12)}`);

  // The primary working tree must be untouched. Sandcastle keeps its own
  // worktrees and logs under .sandcastle/, which every repository that uses
  // agentbox ignores; that entry is expected and is not an agent edit.
  const dirty = git(cfg.repo, ["status", "--porcelain"])
    .split("\n")
    .filter((l) => l.trim() !== "" && !l.includes(".sandcastle/"));
  record("the primary working tree stays clean", dirty.length === 0, dirty[0] ?? "");

  // Leave the worktree clean so Sandcastle can remove it on close, which in
  // turn lets the temporary branch be deleted.
  await sandbox.exec("rm -f SELFTEST_MARKER.txt");
} catch (err) {
  process.stderr.write(`[selftest] failed: ${err?.stack ?? err}\n`);
  exitCode = 1;
} finally {
  if (sandbox) {
    log("destroying the sandbox");
    try {
      await sandbox.close();
      record("the sandbox was destroyed", true);
    } catch (err) {
      record("the sandbox was destroyed", false, err?.message ?? "");
      exitCode = 1;
    }
  }
}

// The sandbox container must be gone.
try {
  const left = execFileSync("podman",
    ["ps", "-a", "--filter", "name=^sandcastle-", "--format", "{{.Names}}"],
    { encoding: "utf8" }).trim();
  record("no sandbox container is left behind", left === "", left);
} catch (err) {
  record("no sandbox container is left behind", false, err?.message ?? "");
}

// The temporary branch is ours; remove it so the pilot repo stays tidy.
try {
  const headAfter = git(cfg.repo, ["rev-parse", "HEAD"]);
  record("the checked-out branch is unchanged after teardown",
    headAfter === headBefore, `${headAfter.slice(0, 12)} vs ${headBefore.slice(0, 12)}`);
  if (cfg.removeBranch !== false) {
    try { git(cfg.repo, ["worktree", "prune"]); } catch { /* nothing to prune */ }
    try { git(cfg.repo, ["branch", "-D", branch]); log(`removed the temporary branch ${branch}`); }
    catch { /* the branch may never have been created */ }
  }
} catch (err) {
  record("the checked-out branch is unchanged after teardown", false, err?.message ?? "");
}

const failed = results.filter((r) => !r.ok);
// A crash before the probes ran leaves an empty result set. That is a
// failure, not a pass: the lifecycle was never proven.
if (exitCode !== 0 || results.length < PROBES.length) {
  log("the lifecycle did not complete; treating the run as failed");
  exitCode = 1;
}
log(`\npassed ${results.length - failed.length}   failed ${failed.length}`);
process.stdout.write(
  `\n===AGENTBOX_SELFTEST_JSON===\n${JSON.stringify({ results }, null, 2)}\n===END===\n`,
);
process.exit(failed.length > 0 ? 1 : exitCode);
