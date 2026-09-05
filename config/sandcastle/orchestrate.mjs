// orchestrate.mjs - the Sandcastle control-plane program.
//
// It runs inside the agent-runner container, which bin/agentbox starts with
// "podman run --rm". It reads one JSON configuration document from the file
// named by AGENTBOX_CONFIG_FILE and drives this lifecycle:
//
//   validate the DISPOSABLE clone
//   -> create the isolated branch and worktree inside it
//   -> create the Podman sandbox
//   -> prove the real repository is not reachable from the sandbox
//   -> run the implementer agent
//   -> deterministic verification
//   -> optional independent reviewer
//   -> deterministic verification
//   -> destroy the sandbox
//
// What it never does, by construction:
//   * touch the real repository. It is never told where that repository is,
//     beyond a list of paths it proves are ABSENT from the sandbox.
//   * push a branch, open or merge a pull request
//   * merge into the checked-out branch
//
// The branch strategy is always an explicit named branch. Sandcastle's
// "head" and "merge-to-head" strategies are never selected here.
//
// The git directory the sandbox holds read-write belongs to the disposable
// clone that bin/agentbox made for this run and deletes afterwards. A ref, a
// config entry or a hook written there reaches nothing else. bin/agentbox
// validates the result on the host and imports only the commits that pass.
//
// The snapshot in clone-integrity.mjs is defense in depth: it records the
// clone's refs, config and hooks before the sandbox exists and compares them
// after it is destroyed, so a run that wrote outside its own branch says so
// out loud even though the write could not leave the run directory.
//
// ESM resolves @ai-hero/sandcastle from /opt/workstation/sandcastle/node_modules,
// which is why bin/agentbox mounts this file into that directory. It mounts
// clone-integrity.mjs beside it for the same reason.

import { createSandbox, claudeCode, codex } from "@ai-hero/sandcastle";
import { podman } from "@ai-hero/sandcastle/sandboxes/podman";
import { readFileSync } from "node:fs";
import {
  diffIntegrity,
  git,
  missingIdentity,
  snapshotIntegrity,
} from "./clone-integrity.mjs";

// --------------------------------------------------------------- utilities --

const log = (msg) => process.stdout.write(`[agentbox] ${msg}\n`);

const fail = (msg) => {
  process.stderr.write(`[agentbox] error: ${msg}\n`);
  process.exit(1);
};

/** Quote one value for a POSIX shell. Every probe path comes from the host
 *  configuration, and a path is allowed to contain a space. */
const shq = (s) => `'${String(s).replaceAll("'", `'\\''`)}'`;

// ----------------------------------------------------------- configuration --
//
// The configuration arrives in a FILE, not in an environment variable and not
// in an argument: a prompt can be long, and nothing about a run belongs in a
// process listing.

const configFile = process.env.AGENTBOX_CONFIG_FILE;
if (!configFile) fail("AGENTBOX_CONFIG_FILE is not set");

/** @type {{
 *   mode: "run" | "pipeline", runId: string,
 *   repo: string, branch: string, baseBranch: string, baseCommit: string,
 *   prompt: string, reviewPrompt?: string, agent: string, model: string,
 *   reviewAgent: "codex" | "claude" | "none", reviewModel: string,
 *   maxIterations: number, checks: string[], sandboxImage: string,
 *   mounts: {hostPath: string, sandboxPath: string, readonly?: boolean}[],
 *   assertIsolation: boolean, timeoutSeconds: number,
 *   credentials: {claude: boolean, codex: boolean}, credentialPath: string,
 *   forbiddenPaths: string[], gitIdentity: {name: string, email: string},
 *   effort?: string
 * }} */
let cfg;
try {
  cfg = JSON.parse(readFileSync(configFile, "utf8"));
} catch (e) {
  fail(`cannot read the configuration from ${configFile}: ${e.message}`);
}

// ------------------------------------------ the disposable clone, validated --

log(`run id           ${cfg.runId}`);
log(`disposable clone ${cfg.repo}`);
log(`branch           ${cfg.branch}`);
log(`base commit      ${cfg.baseCommit.slice(0, 12)}`);
log(`sandbox image    ${cfg.sandboxImage}`);

let currentBranch;
try {
  if (git(cfg.repo, ["rev-parse", "--is-inside-work-tree"]) !== "true") {
    fail(`${cfg.repo} is not a Git working tree`);
  }
  currentBranch = git(cfg.repo, ["rev-parse", "--abbrev-ref", "HEAD"]);
} catch (e) {
  fail(`${cfg.repo} is not a usable Git repository: ${e.message}`);
}

if (cfg.branch === currentBranch) {
  fail(
    `refusing to run: the requested branch "${cfg.branch}" is the branch the ` +
      `disposable clone currently has checked out.`,
  );
}

// The base commit the host resolved must be the one this clone holds. A
// mismatch means the run directory is not the one the configuration describes.
try {
  git(cfg.repo, ["cat-file", "-e", `${cfg.baseCommit}^{commit}`]);
} catch {
  fail(`the base commit ${cfg.baseCommit} is not in ${cfg.repo}`);
}

// --------------------------------------------------- clone integrity, extra --
//
// bin/agentbox owns the boundary: the real repository is not mounted, and the
// host validates every commit before it imports one. This snapshot adds a
// second, cheaper signal. It says whether the run stayed inside its own branch
// while it had the disposable git directory, which is what a well-behaved run
// does and what a hostile one does not.

/** The refname the run is allowed to create or move. */
const agentRef = `refs/heads/${cfg.branch}`;

let integrityBefore;
try {
  integrityBefore = snapshotIntegrity(cfg.repo);
} catch (e) {
  fail(`cannot record the clone integrity baseline: ${e.message}`);
}

// The clone's git directory must be inside the run directory the host made.
// If it is not, this program is pointed at something it must not drive.
if (!integrityBefore.commonDir.startsWith(`${cfg.repo}/`)) {
  fail(
    `the git directory ${integrityBefore.commonDir} is outside the disposable ` +
      `clone ${cfg.repo}. Refusing to run.`,
  );
}

// The clone must already carry the neutral Git identity bin/agentbox gives it
// at clone time. Sandcastle copies user.name and user.email out of this clone
// into the sandbox as part of run(); when it finds none, the agent CLI writes
// its own fallback identity into this git directory the first time it commits,
// which is a configuration change the comparison below would report AFTER the
// work is done. Requiring the identity here turns that into a refusal to
// start, and it is what makes the baseline the identity is measured against.
const identityGap = missingIdentity(integrityBefore.config, cfg.gitIdentity);
if (identityGap.length > 0) {
  fail(
    `the disposable clone has no configured Git identity: ${identityGap.join(", ")} ` +
      "is missing from its local configuration. bin/agentbox sets it at clone " +
      "time, before this baseline is recorded. Refusing to run.",
  );
}

log(
  `clone baseline   ${integrityBefore.refs.length} ref(s), ` +
    `${integrityBefore.hooks.length} hook(s), identity ` +
    `${cfg.gitIdentity.name} <${cfg.gitIdentity.email}>`,
);

// --------------------------------------------------------------- providers --
//
// No credential is passed here, and none is in this process's environment.
// bin/agentbox writes the credential to a file, mode 600, and mounts that file
// read-only into the sandbox. The sandbox image puts a shim in front of the
// agent CLIs; the shim reads the file and exports the value in the CLI's own
// process. A credential value is therefore never an argument to podman, never
// in this container's environment, and never in a process listing.

const agentProvider = (name, model, effort) => {
  const options = effort ? { effort } : {};
  if (name === "claude") return claudeCode(model, options);
  if (name === "codex") return codex(model, options);
  return fail(`unknown agent: ${name}`);
};

const hasCredential = (name) => Boolean(cfg.credentials?.[name]);

if (!hasCredential(cfg.agent)) {
  fail(
    `no credential for the implementer "${cfg.agent}". Put CLAUDE_CODE_OAUTH_TOKEN ` +
      "(from 'claude setup-token') in ~/.config/agentbox/secrets.env. See docs/secrets.md.",
  );
}

const wantsReview = cfg.mode === "pipeline" && cfg.reviewAgent !== "none";
const reviewCredential = wantsReview && hasCredential(cfg.reviewAgent);
if (wantsReview && !reviewCredential) {
  log(`no credential for "${cfg.reviewAgent}"; the review step will be skipped`);
}

const sandboxProvider = podman({
  imageName: cfg.sandboxImage,
  mounts: cfg.mounts ?? [],
  // Bazzite runs SELinux. The shared label lets the rootless container read the
  // bind mounts; it is a no-op on a system without SELinux. Every mount source
  // is inside the per-run directory, so the relabelling lands only on files
  // this run created and this run deletes.
  selinuxLabel: "z",
  // The host user maps to the "agent" user of the image, so bind-mounted files
  // and image-built files both have the right owner without a chown.
  userns: "keep-id",
  containerUid: 1000,
  containerGid: 1000,
});

// -------------------------------------------------------- isolation asserts --

/**
 * Prove, from inside the running sandbox, that no private key material, no
 * host agent socket and no path belonging to the REAL repository reached it.
 */
const assertIsolation = async (sandbox) => {
  const probes = [
    {
      name: "no ~/.ssh directory in the sandbox",
      cmd: "test ! -e ~/.ssh && echo clean || echo LEAK",
    },
    {
      name: "no private key anywhere in the sandbox home",
      cmd: "if find ~ -maxdepth 4 -name 'id_*' ! -name '*.pub' -print -quit 2>/dev/null | grep -q .; then echo LEAK; else echo clean; fi",
    },
    {
      name: "no ssh-agent socket forwarded",
      cmd: 'test -z "$SSH_AUTH_SOCK" && echo clean || echo LEAK',
    },
    {
      name: "no Podman socket reachable from the sandbox",
      cmd: "test ! -S /run/user/1000/podman/podman.sock && echo clean || echo LEAK",
    },
    {
      name: "shared AGENTS.md policy is readable",
      cmd: "head -c 1 ~/.claude/CLAUDE.md >/dev/null 2>&1 && echo clean || echo MISSING",
    },
    {
      name: "the git directory belongs to the disposable clone",
      cmd:
        `case "$(git rev-parse --path-format=absolute --git-common-dir)" in ` +
        `${shq(cfg.repo)}/*) echo clean ;; *) echo LEAK ;; esac`,
    },
    {
      // A sandbox image built before the credential shim existed would pass
      // every probe above and still take its credential from the environment.
      // This is what says the image is the one this checkout describes.
      name: "the credential shim is in front of the agent CLIs",
      cmd:
        'test "$(command -v claude)" = /opt/agents/bin/claude && ' +
        'test "$(command -v codex)" = /opt/agents/bin/codex ' +
        "&& echo clean || echo STALE_IMAGE",
    },
  ];

  // The whole point of the redesign: none of these paths exists in here.
  for (const p of cfg.forbiddenPaths ?? []) {
    probes.push({
      name: `the host path ${p} is absent from the sandbox`,
      cmd: `test ! -e ${shq(p)} && echo clean || echo LEAK`,
    });
  }

  if ((cfg.mounts ?? []).some((m) => m.sandboxPath === "/opt/agents/skills")) {
    probes.push({
      name: "shared skills are readable",
      cmd: "test -d ~/.claude/skills && echo clean || echo MISSING",
    });
  }

  if (cfg.credentialPath) {
    probes.push({
      name: "the credential arrived as a file, not as an environment variable",
      cmd:
        `test -s ${shq(cfg.credentialPath)} && ` +
        `test -z "$CLAUDE_CODE_OAUTH_TOKEN$ANTHROPIC_API_KEY$OPENAI_API_KEY" ` +
        `&& echo clean || echo LEAK`,
    });
  }

  const results = [];
  for (const p of probes) {
    const r = await sandbox.exec(p.cmd);
    const out = `${r.stdout}${r.stderr}`.trim();
    results.push({
      name: p.name,
      ok: r.exitCode === 0 && out.split("\n").pop() === "clean",
      detail: out.split("\n").pop() ?? "",
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
//
// bin/agentbox holds the authoritative wall-clock limit around this whole
// container. The AbortController below is the polite half of the same limit:
// it stops the agent at the deadline so the sandbox can still be destroyed
// and the summary can still be printed.

const deadlineMs = Math.max(30, (cfg.timeoutSeconds ?? 3600) - 60) * 1000;
const abort = new AbortController();
const deadline = setTimeout(() => {
  log(`the wall-clock limit of ${cfg.timeoutSeconds}s is reached; stopping the agent`);
  abort.abort(new Error("agentbox wall-clock timeout"));
}, deadlineMs);
deadline.unref?.();

const summary = {
  runId: cfg.runId,
  repo: cfg.repo,
  branch: cfg.branch,
  baseCommit: cfg.baseCommit,
  mode: cfg.mode,
  implement: null,
  checksAfterImplement: [],
  review: null,
  checksAfterReview: [],
  isolation: [],
  commits: [],
  resultCommit: null,
  checksPassed: null,
  sandboxDestroyed: false,
  cloneIntegrityViolations: null,
  cloneIntact: null,
};

let sandbox;
let exitCode = 0;

try {
  log("creating the sandbox (isolated branch, worktree and container)");
  sandbox = await createSandbox({
    branch: cfg.branch,
    baseBranch: cfg.baseBranch,
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
    signal: abort.signal,
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
          "The implementation branch is still validated and left for human review.",
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
        signal: abort.signal,
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
  clearTimeout(deadline);
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
  summary.resultCommit = git(cfg.repo, ["rev-parse", `refs/heads/${cfg.branch}`]);
  summary.commits = git(cfg.repo, [
    "log", "--format=%H", `${cfg.baseCommit}..${cfg.branch}`,
  ])
    .split("\n")
    .filter(Boolean);
} catch {
  // The branch may not exist when the run failed before the worktree was made.
}

// The clone the sandbox held is disposable, so a write outside the agent
// branch reached nothing. It is still a signal worth failing on: a run that
// tried is a run whose result a human should look at before trusting it.
try {
  const violations = diffIntegrity(integrityBefore, snapshotIntegrity(cfg.repo), agentRef);
  summary.cloneIntegrityViolations = violations;
  summary.cloneIntact = violations.length === 0;
  if (violations.length > 0) {
    exitCode = 1;
    log(`DISPOSABLE CLONE INTEGRITY FAILED: ${violations.length} change(s) outside ${cfg.branch}`);
    for (const v of violations) log(`  ! ${v}`);
    log("The real repository is unaffected: it was never mounted. Nothing will be imported.");
  } else {
    log(`disposable clone integrity: intact (nothing changed outside ${cfg.branch})`);
  }
} catch (err) {
  // Not being able to answer the question is a failure, not a pass.
  exitCode = 1;
  summary.cloneIntact = false;
  summary.cloneIntegrityViolations = [`the integrity check could not run: ${err?.message}`];
  log(`DISPOSABLE CLONE INTEGRITY UNKNOWN: ${err?.message}`);
}

// A failing check is a RESULT, not a crash: the commits are still validated
// and imported either way, and the branch is left for a human. The reviewer is
// deliberately still run, because its job includes fixing a defect the checks
// found. The summary says whether the checks passed.
const allChecks = [...summary.checksAfterImplement, ...summary.checksAfterReview];
summary.checksPassed = allChecks.every((c) => c.exitCode === 0);
const failedChecks = allChecks.filter((c) => c.exitCode !== 0);

log(`commits on ${cfg.branch}: ${summary.commits.length}`);
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
