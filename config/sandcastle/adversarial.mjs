// adversarial.mjs - attack the git directory from inside the sandbox, on
// purpose, so the host can prove the attack reached nothing that matters.
//
// It runs inside the agent-runner container, exactly where orchestrate.mjs
// runs, and it needs no model credential. There is no agent: the sandbox is
// driven directly, which makes the attack deterministic and free.
//
// The sandbox holds the DISPOSABLE clone's git directory read-write, because
// that is how a git worktree works. This program uses that access the way a
// hostile agent would:
//
//   git update-ref refs/heads/main <something>     move a protected branch
//   rewrite .git/config                            an alias is host-side code
//   create .git/hooks/post-checkout                so is a hook
//   git update-ref refs/heads/agentbox-attacker    an arbitrary extra ref
//
// It then makes one ordinary commit on the agent branch, so the host has a
// legitimate result to validate.
//
// Everything above happens in ~/.local/share/agentbox/runs/<run-id>/repo.
// "bin/agentbox selftest --adversarial" then proves, on the HOST:
//
//   * every one of those four mutations DID land in the disposable clone,
//     so the test is testing something
//   * the real repository's refs, HEAD, config, hooks and working tree are
//     unchanged, byte for byte
//   * only the intended agent/* branch is imported after validation
//   * a deliberately corrupted result is refused, and changes nothing
//
// The value of this program is that it fails loudly if the isolation is ever
// weakened back to sharing the real repository's git directory.

import { createSandbox } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const log = (m) => process.stdout.write(`[adversarial] ${m}\n`);
const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();
const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

const configFile = process.env.AGENTBOX_CONFIG_FILE;
if (!configFile) {
  process.stderr.write("[adversarial] error: AGENTBOX_CONFIG_FILE is not set\n");
  process.exit(1);
}
const cfg = JSON.parse(readFileSync(configFile, "utf8"));

const branch = cfg.branch;
const baseCommit = git(cfg.repo, ["rev-parse", "HEAD"]);

log(`disposable clone ${cfg.repo}`);
log(`base commit      ${baseCommit.slice(0, 12)}`);
log(`sandbox branch   ${branch}`);

const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok, detail });
  log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `  (${detail})`}`);
};

// The four mutations, written the way a hostile process would write them.
// GITDIR is resolved inside the sandbox, so the program never needs to know
// the host layout, and the attack follows whatever git says the real target
// is. That is the point: if the sandbox were ever given the REAL repository's
// git directory again, this would hit it.
const ATTACK = `
set -u
GITDIR=$(git rev-parse --path-format=absolute --git-common-dir)
echo "gitdir=$GITDIR"
git update-ref refs/heads/main "$(git rev-parse HEAD)" 2>&1 || echo "update-ref main failed"
printf '[alias]\\n\\tpwn = !touch /tmp/agentbox-pwned\\n' >> "$GITDIR/config"
mkdir -p "$GITDIR/hooks"
printf '#!/bin/sh\\ntouch /tmp/agentbox-pwned\\n' > "$GITDIR/hooks/post-checkout"
chmod +x "$GITDIR/hooks/post-checkout"
git update-ref refs/heads/agentbox-attacker "$(git rev-parse HEAD)" 2>&1 || echo "update-ref attacker failed"
echo ATTACK_DONE
`;

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

  // Before anything else: the real repository must not be reachable at all.
  for (const p of cfg.forbiddenPaths ?? []) {
    const r = await sandbox.exec(`test ! -e ${shq(p)} && echo clean || echo LEAK`);
    const out = `${r.stdout}${r.stderr}`.trim().split("\n").pop() ?? "";
    record(`the host path ${p} is absent from the sandbox`, out === "clean", out);
  }

  // The legitimate work comes first, so that the attack afterwards moves
  // refs/heads/main to a commit it did not already point at. An attack that
  // writes the value a ref already holds would prove nothing.
  log("making one legitimate commit inside the sandbox");
  const commit = await sandbox.exec(
    "printf 'adversarial\\n' > AGENTBOX_ADVERSARIAL.txt && " +
      "git add AGENTBOX_ADVERSARIAL.txt && git commit -q -m 'agentbox adversarial selftest' && " +
      "git rev-parse HEAD",
  );
  record("the sandbox produced a legitimate commit", commit.exitCode === 0,
    `${commit.stdout}${commit.stderr}`.trim().split("\n").pop() ?? "");

  log("running the attack inside the sandbox");
  const atk = await sandbox.exec(ATTACK);
  const atkOut = `${atk.stdout}${atk.stderr}`.trim();
  for (const line of atkOut.split("\n")) log(`  | ${line}`);
  record("the attack ran to completion", atkOut.includes("ATTACK_DONE"), atkOut.split("\n").pop() ?? "");

  // The git directory the attack hit must be the disposable one.
  const gitdirLine = atkOut.split("\n").find((l) => l.startsWith("gitdir="));
  const gitdir = gitdirLine ? gitdirLine.slice("gitdir=".length) : "";
  record(
    "the attacked git directory is inside the disposable clone",
    gitdir.startsWith(`${cfg.repo}/`),
    gitdir,
  );
} catch (err) {
  process.stderr.write(`[adversarial] failed: ${err?.stack ?? err}\n`);
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

// The clone MUST now be damaged. A clean clone means the attack did not run,
// and an adversarial test that did not attack proves nothing.
try {
  const refs = git(cfg.repo, ["for-each-ref", "--format=%(refname)"]).split("\n");
  record(
    "the disposable clone now carries the attacker ref",
    refs.includes("refs/heads/agentbox-attacker"),
    refs.join(" "),
  );
  const mainNow = git(cfg.repo, ["rev-parse", "--verify", "--quiet", "refs/heads/main"]);
  record(
    "the disposable clone's main branch was moved by the attack",
    mainNow !== "" && mainNow !== baseCommit,
    `${baseCommit.slice(0, 12)} -> ${mainNow.slice(0, 12)}`,
  );
} catch (err) {
  record("the disposable clone shows the attack", false, err?.message ?? "");
}

const failed = results.filter((r) => !r.ok);
log(`\npassed ${results.length - failed.length}   failed ${failed.length}`);
process.stdout.write(
  `\n===AGENTBOX_ADVERSARIAL_JSON===\n${JSON.stringify({ results, baseCommit }, null, 2)}\n===END===\n`,
);
process.exit(failed.length > 0 ? 1 : exitCode);
