// orchestrate.mjs - the Sandcastle control-plane program.
//
// It runs inside the agent-runner container, which bin/agentbox starts with
// "podman run --rm". It reads one JSON configuration document from the
// AGENTBOX_CONFIG environment variable and drives this lifecycle:
//
//   validate repository
//   -> create the isolated branch and worktree
//   -> create the Podman sandbox
//   -> run the implementer agent
//   -> deterministic verification
//   -> optional independent reviewer
//   -> deterministic verification
//   -> leave the branch for human review
//   -> destroy the sandbox
//
// What it never does, by construction:
//   * push a branch
//   * open or merge a pull request
//   * merge into the checked-out branch
//
// The branch strategy is always an explicit named branch. Sandcastle's
// "head" and "merge-to-head" strategies are never selected here.
//
// What it CANNOT prevent, and checks for instead:
//   Sandcastle's bind-mount worktree mounts <repo>/.git into the sandbox
//   read-write, because a worktree's ".git" is only a pointer into it. An
//   agent inside the sandbox can therefore write a ref outside "agent/",
//   change .git/config, or install a git hook that later runs on the host.
//   The snapshot below records every ref, the local config and the hook
//   inventory before the sandbox exists, compares them after it is destroyed,
//   and fails the run when anything outside the agent branch moved.
//
// ESM resolves @ai-hero/sandcastle from /opt/workstation/sandcastle/node_modules,
// which is why bin/agentbox mounts this file into that directory.

import { createSandbox, claudeCode, codex } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";

// --------------------------------------------------------------- utilities --

const log = (msg) => process.stdout.write(`[agentbox] ${msg}\n`);

const fail = (msg) => {
  process.stderr.write(`[agentbox] error: ${msg}\n`);
  process.exit(1);
};

const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();

/** git(), but a non-zero exit yields "" instead of throwing.
 *  "symbolic-ref HEAD" exits 1 on a detached HEAD and "config --list" exits 1
 *  when there is no local config file. Both are valid states to record. */
const gitOrEmpty = (repo, args) => {
  try {
    return git(repo, args);
  } catch {
    return "";
  }
};

// ----------------------------------------------------------- configuration --

const raw = process.env.AGENTBOX_CONFIG;
if (!raw) fail("AGENTBOX_CONFIG is not set");

/** @type {{
 *   mode: "run" | "pipeline",
 *   repo: string, branch: string, prompt: string,
 *   reviewPrompt?: string, agent: string, model: string,
 *   reviewAgent: "codex" | "claude" | "none", reviewModel: string,
 *   maxIterations: number, checks: string[],
 *   sandboxImage: string, mounts: {hostPath: string, sandboxPath: string, readonly?: boolean}[],
 *   assertIsolation: boolean, effort?: string
 * }} */
const cfg = JSON.parse(raw);

// ------------------------------------------------------ repository validation --

log(`repository       ${cfg.repo}`);
log(`branch           ${cfg.branch}`);
log(`sandbox image    ${cfg.sandboxImage}`);

let headBefore;
let currentBranch;
try {
  if (git(cfg.repo, ["rev-parse", "--is-inside-work-tree"]) !== "true") {
    fail(`${cfg.repo} is not a Git working tree`);
  }
  currentBranch = git(cfg.repo, ["rev-parse", "--abbrev-ref", "HEAD"]);
  headBefore = git(cfg.repo, ["rev-parse", "HEAD"]);
} catch (e) {
  fail(`${cfg.repo} is not a usable Git repository: ${e.message}`);
}

if (cfg.branch === currentBranch) {
  fail(
    `refusing to run: the requested branch "${cfg.branch}" is the branch the ` +
      `repository currently has checked out. The agent must work on a separate branch.`,
  );
}

log(`checked out      ${currentBranch} @ ${headBefore.slice(0, 12)}`);

// ------------------------------------------------- repository integrity --
//
// Sandcastle's bind-mount worktree gives the sandbox the repository's SHARED
// git directory, read-write: a worktree's ".git" is a file pointing at
// <repo>/.git/worktrees/<name>, so the provider mounts <repo>/.git as well.
// Nothing inside the sandbox is therefore prevented from writing a ref
// outside "agent/", from rewriting .git/config, or from installing a hook
// that would later run on the HOST.
//
// The branch prefix is a policy, not a boundary. This snapshot is what turns
// a violation of that policy from a silent one into a loud one: everything
// except the agent branch is recorded before the sandbox exists and compared
// after it is destroyed. See docs/sandcastle.md, "Honest limits".

const gitCommonDir = () =>
  git(cfg.repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);

/** A file list of <name> <mode> <size> for the hook directory, sorted. */
const hookInventory = (commonDir) => {
  const dir = `${commonDir}/hooks`;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return []; // No hooks directory is a valid state.
  }
  return entries
    .filter((e) => e.isFile() && !e.name.endsWith(".sample"))
    .map((e) => {
      const st = statSync(`${dir}/${e.name}`);
      return `${e.name} ${(st.mode & 0o7777).toString(8)} ${st.size} ${st.mtimeMs}`;
    })
    .sort();
};

/**
 * Everything the agent must not change. Taken before the sandbox is created
 * and again after it is destroyed.
 */
const snapshotIntegrity = () => {
  const commonDir = gitCommonDir();
  return {
    commonDir,
    // Every ref and the object it points at. The agent branch is filtered out
    // of the comparison; every other entry must be identical.
    refs: git(cfg.repo, [
      "for-each-ref", "--format=%(refname) %(objectname)",
    ]).split("\n").filter(Boolean).sort(),
    // Which branch the primary working tree is on.
    head: gitOrEmpty(cfg.repo, ["symbolic-ref", "--quiet", "HEAD"]),
    // .git/config decides what git EXECUTES: aliases, pagers, fsmonitor,
    // credential helpers. A change here is a host-side code-execution change.
    config: gitOrEmpty(cfg.repo, ["config", "--local", "--list"])
      .split("\n").filter(Boolean).sort(),
    hooks: hookInventory(commonDir),
  };
};

/** The refname the agent is allowed to create or move. */
const agentRef = `refs/heads/${cfg.branch}`;

/** Compare two snapshots. Returns a list of human-readable violations. */
const diffIntegrity = (before, after) => {
  const violations = [];
  const withoutAgentBranch = (refs) =>
    refs.filter((r) => !r.startsWith(`${agentRef} `));

  const refsBefore = withoutAgentBranch(before.refs);
  const refsAfter = withoutAgentBranch(after.refs);
  for (const r of refsAfter) {
    if (!refsBefore.includes(r)) violations.push(`ref created or moved: ${r}`);
  }
  for (const r of refsBefore) {
    if (!refsAfter.includes(r)) violations.push(`ref deleted or moved: ${r}`);
  }
  if (before.head !== after.head) {
    violations.push(`the checked-out branch changed: ${before.head} -> ${after.head}`);
  }
  for (const c of after.config) {
    if (!before.config.includes(c)) violations.push(`git config added: ${c}`);
  }
  for (const c of before.config) {
    if (!after.config.includes(c)) violations.push(`git config removed: ${c}`);
  }
  for (const h of after.hooks) {
    if (!before.hooks.includes(h)) violations.push(`git hook added or changed: ${h}`);
  }
  for (const h of before.hooks) {
    if (!after.hooks.includes(h)) violations.push(`git hook removed: ${h}`);
  }
  return violations;
};

// Taken BEFORE anything is created. A repository this cannot be read from is
// not one an unattended agent should be pointed at, so this failure is fatal
// and happens while nothing has been changed yet.
let integrityBefore;
try {
  integrityBefore = snapshotIntegrity();
} catch (e) {
  fail(`cannot record the repository integrity baseline: ${e.message}`);
}
log(`integrity baseline ${integrityBefore.refs.length} ref(s), ` +
    `${integrityBefore.hooks.length} hook(s)`);

// --------------------------------------------------------------- providers --

// Credentials reach the sandbox through the SANDBOX provider, not the agent
// provider.
//
// The provider builds the container with "podman run -e ...", and drives it
// afterwards with "podman exec", which passes no environment of its own. The
// container environment is therefore fixed when the sandbox is created. With
// createSandbox() the agent is not known yet at that moment, so an agent
// provider's env would arrive too late and the CLI would report "Not logged
// in". The sandbox provider's env is applied at create time, which is what the
// implementer and the reviewer both need.
//
// Sandcastle throws when the agent env and the sandbox env share a key, so the
// credentials live in exactly one of the two: the sandbox.

const claudeCredential = () => {
  const token = process.env.CLAUDE_CODE_OAUTH_TOKEN;
  if (token) return { CLAUDE_CODE_OAUTH_TOKEN: token };
  const key = process.env.ANTHROPIC_API_KEY;
  if (key) return { ANTHROPIC_API_KEY: key };
  return null;
};

const codexCredential = () => {
  const key = process.env.OPENAI_API_KEY;
  return key ? { OPENAI_API_KEY: key } : null;
};

const credentialFor = (name) =>
  name === "claude" ? claudeCredential() : name === "codex" ? codexCredential() : null;

/** Build the agent provider. The credential is already in the container env. */
const agentProvider = (name, model, effort) => {
  const options = effort ? { effort } : {};
  if (name === "claude") return claudeCode(model, options);
  if (name === "codex") return codex(model, options);
  return fail(`unknown agent: ${name}`);
};

// Fail before anything is created when the implementer has no credential.
const implementCredential = credentialFor(cfg.agent);
if (!implementCredential) {
  fail(
    `no credential for the implementer "${cfg.agent}". Put CLAUDE_CODE_OAUTH_TOKEN ` +
      "(from 'claude setup-token') in ~/.config/agentbox/secrets.env. See docs/secrets.md.",
  );
}

// The reviewer shares the container, so its credential has to be present at
// create time too. When it is absent the review step is skipped, not failed.
const wantsReview = cfg.mode === "pipeline" && cfg.reviewAgent !== "none";
const reviewCredential = wantsReview ? credentialFor(cfg.reviewAgent) : null;
if (wantsReview && !reviewCredential) {
  log(`no credential for "${cfg.reviewAgent}"; the review step will be skipped`);
}

const sandboxEnv = { ...implementCredential, ...(reviewCredential ?? {}) };

const sandboxProvider = podman({
  imageName: cfg.sandboxImage,
  env: sandboxEnv,
  mounts: cfg.mounts ?? [],
  // Bazzite runs SELinux. The shared label lets the rootless container read the
  // bind mounts; it is a no-op on a system without SELinux.
  selinuxLabel: "z",
  // The host user maps to the "agent" user of the image, so bind-mounted files
  // and image-built files both have the right owner without a chown.
  userns: "keep-id",
  containerUid: 1000,
  containerGid: 1000,
});

// -------------------------------------------------------- isolation asserts --

/**
 * Prove, from inside the running sandbox, that no private key material and no
 * host agent socket reached it. Returns a list of {name, ok, detail}.
 */
const assertIsolation = async (sandbox) => {
  const probes = [
    {
      name: "no ~/.ssh directory in the sandbox",
      cmd: "test ! -e ~/.ssh && echo clean || (echo LEAK; ls -la ~/.ssh)",
    },
    {
      name: "no private key anywhere in the sandbox home",
      cmd: "if find ~ -maxdepth 4 -name 'id_*' ! -name '*.pub' -print -quit 2>/dev/null | grep -q .; then echo LEAK; else echo clean; fi",
    },
    {
      name: "no ssh-agent socket forwarded",
      cmd: "test -z \"$SSH_AUTH_SOCK\" && echo clean || echo LEAK",
    },
    {
      name: "no Podman socket reachable from the sandbox",
      cmd: "test ! -S /run/user/1000/podman/podman.sock && echo clean || echo LEAK",
    },
    {
      name: "shared AGENTS.md policy is readable",
      cmd: "head -1 ~/.claude/CLAUDE.md >/dev/null && echo clean || echo MISSING",
    },
    {
      name: "shared skills are readable",
      cmd: "test -d ~/.claude/skills && ls ~/.claude/skills | head -1 >/dev/null && echo clean || echo MISSING",
    },
  ];

  const results = [];
  for (const p of probes) {
    const r = await sandbox.exec(p.cmd);
    const out = `${r.stdout}${r.stderr}`.trim();
    results.push({
      name: p.name,
      ok: r.exitCode === 0 && out.startsWith("clean"),
      detail: out.split("\n")[0] ?? "",
    });
  }
  return results;
};

// --------------------------------------------------------- deterministic checks --

const runChecks = async (sandbox, label) => {
  const results = [];
  for (const cmd of cfg.checks ?? []) {
    log(`${label}: ${cmd}`);
    const r = await sandbox.exec(cmd);
    results.push({ command: cmd, exitCode: r.exitCode });
    if (r.exitCode !== 0) {
      const tail = `${r.stdout}\n${r.stderr}`.trim().split("\n").slice(-30).join("\n");
      log(`${label}: FAILED (exit ${r.exitCode})\n${tail}`);
    } else {
      log(`${label}: ok`);
    }
  }
  return results;
};

// --------------------------------------------------------------------- main --

const summary = {
  repo: cfg.repo,
  branch: cfg.branch,
  mode: cfg.mode,
  headBefore,
  currentBranch,
  implement: null,
  checksAfterImplement: [],
  review: null,
  checksAfterReview: [],
  isolation: [],
  commits: [],
  checksPassed: null,
  sandboxDestroyed: false,
  headAfter: null,
  mainUnchanged: null,
  integrityViolations: null,
  repositoryIntact: null,
};

let sandbox;
let exitCode = 0;

try {
  log("creating the sandbox (isolated branch, worktree and container)");
  sandbox = await createSandbox({
    branch: cfg.branch,
    sandbox: sandboxProvider,
    cwd: cfg.repo,
  });
  log(`worktree         ${sandbox.worktreePath}`);

  if (cfg.assertIsolation) {
    log("running the isolation probes");
    summary.isolation = await assertIsolation(sandbox);
    for (const r of summary.isolation) {
      log(`  ${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.ok ? "" : ` (${r.detail})`}`);
    }
    if (summary.isolation.some((r) => !r.ok)) {
      throw new Error("an isolation probe failed; the sandbox is not safe to use");
    }
  }

  // ------------------------------------------------------------- implement --
  log(`running the implementer (${cfg.agent} ${cfg.model})`);
  const impl = await sandbox.run({
    name: "implementer",
    agent: agentProvider(cfg.agent, cfg.model, cfg.effort),
    prompt: cfg.prompt,
    maxIterations: cfg.maxIterations ?? 1,
    logging: { type: "stdout" },
  });
  summary.implement = {
    iterations: impl.iterations.length,
    commits: impl.commits.map((c) => c.sha),
    completionSignal: impl.completionSignal ?? null,
  };
  log(`implementer made ${impl.commits.length} commit(s)`);

  // -------------------------------------------------- deterministic checks --
  summary.checksAfterImplement = await runChecks(sandbox, "check after implement");

  // ---------------------------------------------------------------- review --
  if (wantsReview) {
    if (!reviewCredential) {
      log(
        `skipping the independent review: no credential for "${cfg.reviewAgent}". ` +
          "The implementation branch is still left for human review.",
      );
      summary.review = { skipped: true, reason: "no credential" };
    } else {
      log(`running the independent reviewer (${cfg.reviewAgent} ${cfg.reviewModel})`);
      const rev = await sandbox.run({
        name: "reviewer",
        agent: agentProvider(cfg.reviewAgent, cfg.reviewModel, cfg.effort),
        prompt: cfg.reviewPrompt,
        maxIterations: 1,
        logging: { type: "stdout" },
      });
      summary.review = {
        skipped: false,
        iterations: rev.iterations.length,
        commits: rev.commits.map((c) => c.sha),
      };
      summary.checksAfterReview = await runChecks(sandbox, "check after review");
    }
  }
} catch (err) {
  process.stderr.write(`[agentbox] run failed: ${err?.stack ?? err}\n`);
  exitCode = 1;
} finally {
  if (sandbox) {
    log("destroying the sandbox");
    try {
      const closed = await sandbox.close();
      summary.sandboxDestroyed = true;
      if (closed?.preservedWorktreePath) {
        log(`worktree preserved (uncommitted changes): ${closed.preservedWorktreePath}`);
      }
    } catch (err) {
      process.stderr.write(`[agentbox] sandbox teardown failed: ${err?.message}\n`);
      exitCode = 1;
    }
  }
}

// ------------------------------------------------------------- final report --

try {
  summary.headAfter = git(cfg.repo, ["rev-parse", "HEAD"]);
  summary.mainUnchanged = summary.headAfter === headBefore;
  summary.commits = git(cfg.repo, [
    "log", "--format=%H", `${headBefore}..${cfg.branch}`,
  ])
    .split("\n")
    .filter(Boolean);
} catch {
  // The branch may not exist when the run failed before the worktree was made.
}

// -------------------------------------------------- repository integrity --
//
// The sandbox held the repository's shared git directory read-write, so the
// agent/ prefix could not stop a write outside it. This is the check that says
// whether one happened. It runs AFTER teardown, and it fails the run: a
// repository whose refs, config or hooks moved is one a human must look at
// before trusting anything on the branch.
try {
  const violations = diffIntegrity(integrityBefore, snapshotIntegrity());
  summary.integrityViolations = violations;
  summary.repositoryIntact = violations.length === 0;
  if (violations.length > 0) {
    exitCode = 1;
    log(`REPOSITORY INTEGRITY FAILED: ${violations.length} change(s) outside ${cfg.branch}`);
    for (const v of violations) log(`  ! ${v}`);
    log("Inspect the repository before you use this branch.");
  } else {
    log(`repository integrity: intact (nothing changed outside ${cfg.branch})`);
  }
} catch (err) {
  // Not being able to answer the question is a failure, not a pass.
  exitCode = 1;
  summary.repositoryIntact = false;
  summary.integrityViolations = [`the integrity check could not run: ${err?.message}`];
  log(`REPOSITORY INTEGRITY UNKNOWN: ${err?.message}`);
}

// A failing check is a RESULT, not a crash: the branch is still left for a
// human either way. The reviewer is deliberately still run, because its job
// includes fixing a defect the checks found. The exit code stays 0 for a run
// that completed; the summary says whether the checks passed.
const allChecks = [...summary.checksAfterImplement, ...summary.checksAfterReview];
summary.checksPassed = allChecks.every((c) => c.exitCode === 0);
const failedChecks = allChecks.filter((c) => c.exitCode !== 0);

log(`branch left for human review: ${cfg.branch} (${summary.commits.length} commit(s))`);
log(`checked-out branch unchanged: ${summary.mainUnchanged}`);
if (allChecks.length === 0) {
  log(
    (cfg.checks ?? []).length === 0
      ? "deterministic checks: none were configured (pass --check)"
      : "deterministic checks: configured, but the run stopped before they could run",
  );
} else if (summary.checksPassed) {
  log(`deterministic checks: all ${allChecks.length} passed`);
} else {
  log(`deterministic checks: ${failedChecks.length} of ${allChecks.length} FAILED`);
  for (const c of failedChecks) log(`  failed: ${c.command} (exit ${c.exitCode})`);
}

process.stdout.write(
  `\n===AGENTBOX_SUMMARY_JSON===\n${JSON.stringify(summary, null, 2)}\n===END===\n`,
);

process.exit(exitCode);
