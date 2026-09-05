// selftest.mjs - prove the sandbox lifecycle without calling an agent.
//
// It runs inside the agent-runner container. It exercises every step of the
// agentbox lifecycle except the agent invocation itself, so it needs no model
// credential and costs nothing:
//
//   create the isolated branch and worktree inside the DISPOSABLE clone
//   -> create the Podman sandbox
//   -> prove no key material and no Podman socket reached the sandbox
//   -> prove no path of the REAL repository is reachable from the sandbox
//   -> prove the staged policy and skills are readable
//   -> run the deterministic checks
//   -> make one ordinary commit, so the host has something to import
//   -> destroy the sandbox
//
// bin/agentbox selftest drives it, and then proves on the HOST that the real
// repository did not move and that the commit imports cleanly.

import { createSandbox } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const log = (m) => process.stdout.write(`[selftest] ${m}\n`);
const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();
const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

/** Sandcastle sets a git identity in the sandbox as part of run(). This file
 *  never calls run(), so it carries its own. */
const GIT_IDENTITY = "-c user.name=agentbox -c user.email=agentbox@localhost";

const configFile = process.env.AGENTBOX_CONFIG_FILE;
if (!configFile) {
  process.stderr.write("[selftest] error: AGENTBOX_CONFIG_FILE is not set\n");
  process.exit(1);
}
const cfg = JSON.parse(readFileSync(configFile, "utf8"));
if (!cfg.repo) {
  process.stderr.write("[selftest] error: the configuration has no repo\n");
  process.exit(1);
}

const branch = cfg.branch;
const headBefore = git(cfg.repo, ["rev-parse", "HEAD"]);

log(`disposable clone ${cfg.repo}`);
log(`base commit      ${headBefore.slice(0, 12)}`);
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
  ["no credential in the sandbox environment",
   'test -z "$CLAUDE_CODE_OAUTH_TOKEN$ANTHROPIC_API_KEY$OPENAI_API_KEY" && echo clean || echo LEAK'],
  ["the staged AGENTS.md policy is readable",
   "head -c 1 ~/.claude/CLAUDE.md >/dev/null 2>&1 && echo clean || echo MISSING"],
  ["the sandbox is not privileged",
   "if capsh --print 2>/dev/null | grep -q 'cap_sys_admin'; then echo LEAK; else echo clean; fi"],
  ["the worktree is mounted and is a git worktree",
   "git rev-parse --is-inside-work-tree >/dev/null 2>&1 && echo clean || echo MISSING"],
  ["the git directory belongs to the disposable clone",
   `case "$(git rev-parse --path-format=absolute --git-common-dir)" in ${shq(cfg.repo)}/*) echo clean ;; *) echo LEAK ;; esac`],
  // A sandbox image built before the credential shim existed would pass every
  // probe above and still take its credential from the environment. This is
  // what says the image is the one this checkout describes.
  ["the credential shim is in front of the agent CLIs",
   'test "$(command -v claude)" = /opt/agents/bin/claude && test "$(command -v codex)" = /opt/agents/bin/codex && echo clean || echo STALE_IMAGE'],
];

if ((cfg.mounts ?? []).some((m) => m.sandboxPath === "/opt/agents/skills")) {
  PROBES.push([
    "the staged skill store is readable",
    "test -d ~/.claude/skills && echo clean || echo MISSING",
  ]);
}

for (const p of cfg.forbiddenPaths ?? []) {
  PROBES.push([
    `the host path ${p} is absent from the sandbox`,
    `test ! -e ${shq(p)} && echo clean || echo LEAK`,
  ]);
}

let sandbox;
let exitCode = 0;

try {
  log("creating the sandbox");
  sandbox = await createSandbox({
    branch,
    baseBranch: cfg.baseBranch,
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

  // One ordinary commit, so the host side has a real result to validate and
  // import. Everything up to here proved what the sandbox cannot reach; this
  // proves the path that a real run takes.
  // The identity is explicit. bin/agentbox gives the clone one, and Sandcastle
  // copies it into the sandbox as part of run(), which drives an agent;
  // createSandbox() and exec() do not. Naming it here keeps this test from
  // depending on either of those, and keeps its commit distinguishable from a
  // commit an agent made.
  log("making one commit inside the sandbox");
  const commit = await sandbox.exec(
    "printf 'selftest\\n' > AGENTBOX_SELFTEST.txt && git add AGENTBOX_SELFTEST.txt && " +
      `git ${GIT_IDENTITY} commit -q -m 'agentbox selftest' && git rev-parse HEAD`,
  );
  record("the sandbox produced a commit", commit.exitCode === 0,
    `${commit.stdout}${commit.stderr}`.trim().split("\n").pop() ?? "");
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
