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
//   * write to any branch other than the requested one
//
// The branch strategy is always an explicit named branch. Sandcastle's
// "head" and "merge-to-head" strategies are never selected here.
//
// ESM resolves @ai-hero/sandcastle from /opt/workstation/sandcastle/node_modules,
// which is why bin/agentbox mounts this file into that directory.

import { createSandbox, claudeCode, codex } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { execFileSync } from "node:child_process";

// --------------------------------------------------------------- utilities --

const log = (msg) => process.stdout.write(`[agentbox] ${msg}\n`);

const fail = (msg) => {
  process.stderr.write(`[agentbox] error: ${msg}\n`);
  process.exit(1);
};

const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();

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

// --------------------------------------------------------------- providers --

/** Build the agent provider for a name, with its credential passed as env. */
const agentProvider = (name, model, effort) => {
  if (name === "claude") {
    const token = process.env.CLAUDE_CODE_OAUTH_TOKEN;
    const key = process.env.ANTHROPIC_API_KEY;
    if (!token && !key) {
      fail(
        "no Claude credential. Set CLAUDE_CODE_OAUTH_TOKEN (run 'claude setup-token') " +
          "in ~/.config/agentbox/secrets.env. See docs/secrets.md.",
      );
    }
    const env = token
      ? { CLAUDE_CODE_OAUTH_TOKEN: token }
      : { ANTHROPIC_API_KEY: key };
    return claudeCode(model, effort ? { effort, env } : { env });
  }
  if (name === "codex") {
    const key = process.env.OPENAI_API_KEY;
    if (!key) {
      fail(
        "no Codex credential. Set OPENAI_API_KEY in ~/.config/agentbox/secrets.env. " +
          "The interactive ~/.codex/auth.json is deliberately NOT mounted into a sandbox.",
      );
    }
    const env = { OPENAI_API_KEY: key };
    return codex(model, effort ? { effort, env } : { env });
  }
  return fail(`unknown agent: ${name}`);
};

const sandboxProvider = podman({
  imageName: cfg.sandboxImage,
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
  if (cfg.mode === "pipeline" && cfg.reviewAgent !== "none") {
    const hasKey =
      cfg.reviewAgent === "codex"
        ? Boolean(process.env.OPENAI_API_KEY)
        : Boolean(process.env.CLAUDE_CODE_OAUTH_TOKEN || process.env.ANTHROPIC_API_KEY);

    if (!hasKey) {
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
  log("deterministic checks: none were configured (pass --check)");
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
