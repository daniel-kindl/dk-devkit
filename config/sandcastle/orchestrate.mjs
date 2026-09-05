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
//   -> feed a failing check back to the SAME agent, up to maxFixRounds times
//   -> optional independent reviewer
//   -> deterministic verification
//   -> destroy the sandbox
//
// The fix loop is the feedback half of the implementation phase. Sandcastle
// keeps one sandbox across several run() calls, and commits accumulate on the
// same branch, so a repair costs one more agent turn and nothing else. A
// repair that needed a new clone would cost a whole run.
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
import { mkdirSync, readFileSync } from "node:fs";
import {
  diffIntegrity,
  git,
  missingIdentity,
  preservedWorktreeLines,
  snapshotIntegrity,
  worktreeStatus,
} from "./clone-integrity.mjs";

// --------------------------------------------------------------- utilities --

const log = (msg) => process.stdout.write(`[agentbox] ${msg}\n`);

// The structured progress channel.
//
// A coordinator needs to know which phase a run is in, and it must not learn
// that by reading prose. Every transition below is published as one line:
//
//     ===AGENTBOX_EVENT=== {"event":"implement.start","agent":"claude"}
//
// The prefix is exact and the payload is JSON, so a reader matches a prefix
// and parses a document. Nothing a model prints can produce one of these
// lines with a meaning of its own: the events are emitted by this file, at
// points this file reaches, and they carry only what this file knows.
const event = (name, data = {}) =>
  process.stdout.write(
    `===AGENTBOX_EVENT=== ${JSON.stringify({ event: name, ...data })}\n`,
  );

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

/** How the agent's own output is handled.
 *
 *   "terminal"  Sandcastle renders its interactive terminal UI on stdout.
 *               This is the default, and it is what a human at a terminal
 *               running bin/agentbox directly wants to see.
 *
 *   "progress"  Sandcastle writes a log file, and this file forwards the
 *               agent's text and tool calls as plain lines while publishing
 *               throttled progress events. A coordinator that captures stdout
 *               asks for this: an interactive UI in a pipe is control codes,
 *               not evidence, and it carries no iteration number.
 *
 * The two modes change WHERE output goes. Neither changes what the agent does,
 * what is committed, or what is imported.
 */
const AGENT_OUTPUT_MODES = ["terminal", "progress"];

/** At most one progress event per this many milliseconds, per phase. A new
 *  iteration always publishes at once, because that is a real transition. */
const PROGRESS_INTERVAL_MS = 20_000;

const configFile = process.env.AGENTBOX_CONFIG_FILE;
if (!configFile) fail("AGENTBOX_CONFIG_FILE is not set");

/** @type {{
 *   mode: "run" | "pipeline", runId: string,
 *   repo: string, branch: string, baseBranch: string, baseCommit: string,
 *   prompt: string, reviewPrompt?: string, agent: string, model: string,
 *   reviewAgent: "codex" | "claude" | "none", reviewModel: string,
 *   maxIterations: number, maxFixRounds?: number,
 *   checks: string[], sandboxImage: string,
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

cfg.agentOutput = cfg.agentOutput ?? "terminal";
if (!AGENT_OUTPUT_MODES.includes(cfg.agentOutput)) {
  fail(`unknown agentOutput: ${cfg.agentOutput}`);
}

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

// A failing check keeps a bounded tail of its output. That tail is the whole
// input of a repair: the agent is told what failed and what it printed, and
// nothing else. The bound matters because a full test log is far longer than
// a prompt should be.
const TAIL_LINES = 40;
const TAIL_BYTES = 4000;

const tailOf = (result) => {
  const text = `${result.stdout}\n${result.stderr}`.trim();
  const lines = text.split("\n").slice(-TAIL_LINES).join("\n");
  return lines.length > TAIL_BYTES ? lines.slice(-TAIL_BYTES) : lines;
};

const failuresIn = (results) => results.filter((r) => r.exitCode !== 0);

const runChecks = async (sandbox, label) => {
  const results = [];
  const all = cfg.checks ?? [];
  let index = 0;
  for (const cmd of all) {
    index += 1;
    log(`${label}: ${cmd}`);
    event("check.start", { command: cmd, index, total: all.length, label });
    const r = await sandbox.exec(cmd);
    const entry = { command: cmd, exitCode: r.exitCode };
    if (r.exitCode !== 0) {
      entry.tail = tailOf(r);
      log(`${label}: FAILED (exit ${r.exitCode})\n${entry.tail}`);
    } else {
      log(`${label}: ok`);
    }
    event("check.done", { command: cmd, exitCode: r.exitCode, index, total: all.length });
    results.push(entry);
  }
  event("checks.done", {
    label,
    total: results.length,
    failed: failuresIn(results).length,
  });
  return results;
};

// --------------------------------------------------------- the agent output --

/** The logging option for one agent run, and the progress it publishes.
 *
 * In "terminal" mode this is exactly what it always was. In "progress" mode
 * Sandcastle writes the log to a file inside the disposable clone, and the
 * callback does two things: it forwards what the agent said as plain lines,
 * so a captured stdout keeps the same evidence it kept before, and it
 * publishes a throttled progress event carrying the ITERATION NUMBER, which
 * is the only place that number exists.
 */
const agentLogging = (name, phase, maxIterations) => {
  if (cfg.agentOutput !== "progress") return { type: "stdout" };
  const dir = `${cfg.repo}/.sandcastle/logs`;
  try {
    mkdirSync(dir, { recursive: true });
  } catch {
    /* Sandcastle creates it too; a race here is not a failure. */
  }
  let lastAt = 0;
  let lastIteration = 0;
  let tools = 0;
  const publish = (iteration, force) => {
    const now = Date.now();
    if (!force && now - lastAt < PROGRESS_INTERVAL_MS) return;
    lastAt = now;
    lastIteration = iteration;
    event("agent.progress", {
      phase,
      agent: phase === "review" ? cfg.reviewAgent : cfg.agent,
      iteration,
      maxIterations,
      tools,
    });
  };
  return {
    type: "file",
    path: `${dir}/${name}.log`,
    onAgentStreamEvent: (e) => {
      const iteration = typeof e.iteration === "number" ? e.iteration : lastIteration;
      if (e.type === "text") {
        for (const line of String(e.message ?? "").split("\n")) {
          if (line.trim()) process.stdout.write(`[agent:${name}] ${line}\n`);
        }
      } else if (e.type === "toolCall") {
        tools += 1;
        process.stdout.write(`[agent:${name}] $ ${e.name} ${e.formattedArgs ?? ""}\n`);
      } else {
        return; // "raw" is the debug stream; --agent-output terminal shows it
      }
      publish(iteration, iteration !== lastIteration);
    },
  };
};

/** The instruction for one repair turn. Strict, because no human reads it. */
const fixPrompt = (failures, round, rounds) => {
  const evidence = failures
    .map((f) => `#### ${f.command}  (exit ${f.exitCode})\n\n\`\`\`\n${f.tail ?? ""}\n\`\`\``)
    .join("\n\n");
  return `# Task: repair the failing checks

You implemented a change in this worktree. The repository checks then failed.
This is repair round ${round} of ${rounds}.

## What to do

1. Read the evidence below.
2. Find the cause of each failure. Fix the cause.
3. Run the failing command again. Repeat until it passes.
4. Commit the fix.

## Limits

Fix the failure. Change nothing else. Do not delete a test. Do not weaken a
test. Do not mark a test as skipped to make the run green.

Report the reason in your commit message if the failure has a cause outside
your change.

## Evidence

${evidence}
`;
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

// -------------------------------------------------- the preserved worktree --
//
// Sandcastle keeps a worktree it cannot remove cleanly instead of deleting it.
// That is correct, and it is not weakened here. What is added is the evidence:
// the run directory, and the preserved worktree inside it, are removed by
// bin/agentbox as soon as the run succeeds, so a bare path in the log points
// at nothing by the time anyone reads it.
//
// Two producers are already known and neither is a defect in this program:
//
//   * .pnpm-store/ - pnpm put its content-addressable store in the repository
//     because the worktree is its own mount point. The sandbox image pins
//     store-dir, so this appears only on an image built before SANDBOX_TAG
//     0.2.0.
//   * pnpm-lock.yaml - "pnpm install" writes it, and a repository that
//     neither commits nor ignores its lockfile leaves it untracked on every
//     run. That is the target repository's gap to close, not this one's.
//
// Anything else on this list is worth a human's attention, which is the whole
// reason the list is printed.

const reportPreservedWorktree = (path) => {
  log(`worktree preserved (uncommitted changes): ${path}`);
  let entries;
  try {
    entries = worktreeStatus(path);
  } catch (err) {
    summary.preservedWorktree = { path, entries: null, error: String(err?.message ?? err) };
    log(`  the status of the worktree could not be read: ${err?.message ?? err}`);
    return;
  }
  summary.preservedWorktree = { path, entries };
  for (const line of preservedWorktreeLines(entries)) log(line);
  log("  nothing here is imported, and the run directory removes it");
};

const summary = {
  runId: cfg.runId,
  repo: cfg.repo,
  branch: cfg.branch,
  baseCommit: cfg.baseCommit,
  mode: cfg.mode,
  implement: null,
  checksAfterImplement: [],
  fixRounds: 0,
  fixes: [],
  checksAfterFix: [],
  review: null,
  checksAfterReview: [],
  isolation: [],
  commits: [],
  resultCommit: null,
  checksPassed: null,
  sandboxDestroyed: false,
  cloneIntegrityViolations: null,
  cloneIntact: null,
  preservedWorktree: null,
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
  event("sandbox.ready", { branch: cfg.branch });

  if (cfg.assertIsolation) {
    log("running the isolation probes");
    summary.isolation = await assertIsolation(sandbox);
    for (const r of summary.isolation) {
      log(`  ${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.ok ? "" : ` (${r.detail})`}`);
    }
    const failedProbes = summary.isolation.filter((r) => !r.ok);
    event(failedProbes.length ? "isolation.failed" : "isolation.ok", {
      probes: summary.isolation.length,
      failed: failedProbes.length,
    });
    if (failedProbes.length > 0) {
      throw new Error("an isolation probe failed; the sandbox is not safe to use");
    }
  }

  // ------------------------------------------------------------- implement --
  log(`running the implementer (${cfg.agent} ${cfg.model})`);
  event("implement.start", {
    agent: cfg.agent,
    model: cfg.model,
    maxIterations: cfg.maxIterations ?? 1,
  });
  const impl = await sandbox.run({
    name: "implementer",
    agent: agentProvider(cfg.agent, cfg.model, cfg.effort),
    prompt: cfg.prompt,
    maxIterations: cfg.maxIterations ?? 1,
    logging: agentLogging("implementer", "implement", cfg.maxIterations ?? 1),
    signal: abort.signal,
  });
  summary.implement = {
    iterations: impl.iterations.length,
    commits: impl.commits.map((c) => c.sha),
    completionSignal: impl.completionSignal ?? null,
  };
  log(`implementer made ${impl.commits.length} commit(s)`);
  event("implement.done", {
    commits: impl.commits.length,
    iterations: impl.iterations.length,
  });

  // -------------------------------------------------- deterministic checks --
  summary.checksAfterImplement = await runChecks(sandbox, "check after implement");

  // ------------------------------------------------------------- fix loop --
  //
  // The feedback half of the implementation phase. A failing check goes back
  // to the SAME agent, in the SAME sandbox, with the failing command and the
  // tail of its output as the whole evidence. The loop stops when the checks
  // pass or when the round budget runs out. Either way the branch is still
  // validated and imported, and the summary says which happened.
  const maxFixRounds = Math.max(0, cfg.maxFixRounds ?? 0);
  let latestChecks = summary.checksAfterImplement;
  while (summary.fixRounds < maxFixRounds && failuresIn(latestChecks).length > 0) {
    const round = summary.fixRounds + 1;
    const failures = failuresIn(latestChecks);
    log(
      `${failures.length} check(s) failed; repair round ${round} of ${maxFixRounds}`,
    );
    event("fix.start", {
      round,
      maxRounds: maxFixRounds,
      failed: failures.length,
    });
    const fix = await sandbox.run({
      name: `fix-${round}`,
      agent: agentProvider(cfg.agent, cfg.model, cfg.effort),
      prompt: fixPrompt(failures, round, maxFixRounds),
      maxIterations: cfg.maxIterations ?? 1,
      logging: agentLogging(`fix-${round}`, "fix", cfg.maxIterations ?? 1),
      signal: abort.signal,
    });
    summary.fixRounds = round;
    summary.fixes.push({
      round,
      iterations: fix.iterations.length,
      commits: fix.commits.map((c) => c.sha),
      repaired: failures.map((f) => f.command),
    });
    latestChecks = await runChecks(sandbox, `check after fix ${round}`);
    summary.checksAfterFix.push(...latestChecks);
    event("fix.done", { round, commits: fix.commits.length });
  }
  if (summary.fixRounds > 0) {
    log(
      failuresIn(latestChecks).length === 0
        ? `the checks pass after ${summary.fixRounds} repair round(s)`
        : `the checks still fail after ${summary.fixRounds} repair round(s)`,
    );
  }

  // ---------------------------------------------------------------- review --
  if (!wantsReview) {
    event("review.skipped", {
      reason:
        cfg.reviewAgent === "none"
          ? "the review agent is none"
          : "this is not a pipeline run",
    });
  }
  if (wantsReview) {
    if (!reviewCredential) {
      log(
        `skipping the independent review: no credential for "${cfg.reviewAgent}". ` +
          "The implementation branch is still validated and left for human review.",
      );
      summary.review = { skipped: true, reason: "no credential" };
      event("review.skipped", {
        reason: `no ${cfg.reviewAgent} credential`,
        agent: cfg.reviewAgent,
      });
    } else {
      log(`running the independent reviewer (${cfg.reviewAgent} ${cfg.reviewModel})`);
      event("review.start", { agent: cfg.reviewAgent, model: cfg.reviewModel });
      const rev = await sandbox.run({
        name: "reviewer",
        agent: agentProvider(cfg.reviewAgent, cfg.reviewModel, cfg.effort),
        prompt: cfg.reviewPrompt,
        maxIterations: 1,
        logging: agentLogging("reviewer", "review", 1),
        signal: abort.signal,
      });
      summary.review = {
        skipped: false,
        iterations: rev.iterations.length,
        commits: rev.commits.map((c) => c.sha),
      };
      event("review.done", { commits: rev.commits.length });
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
        reportPreservedWorktree(closed.preservedWorktreePath);
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
    event("integrity.failed", { violations: violations.length });
  } else {
    log(`disposable clone integrity: intact (nothing changed outside ${cfg.branch})`);
    event("integrity.ok", {});
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
// The LAST state of the checks decides, not every state they passed through.
// A run that failed a check, repaired itself and then passed is a pass, and
// reporting it as a failure would send the coordinator into a repair loop of
// its own for work that is already correct.
const finalChecks =
  summary.checksAfterReview.length > 0
    ? summary.checksAfterReview
    : summary.checksAfterFix.length > 0
      ? summary.checksAfterFix.slice(-(cfg.checks ?? []).length || undefined)
      : summary.checksAfterImplement;
const allChecks = finalChecks;
summary.checksPassed =
  allChecks.length === 0 ? null : allChecks.every((c) => c.exitCode === 0);
const failedChecks = allChecks.filter((c) => c.exitCode !== 0);

// The consumer of this summary is bin/agentq, and it needs exactly two
// things: whether the checks pass now, and what to put in a repair prompt if
// they do not. Both are published here, so the reader never has to guess
// which of the per-phase arrays is the current one.
summary.finalChecks = finalChecks;
summary.failedChecks = failedChecks.map((c) => ({
  command: c.command,
  exitCode: c.exitCode,
  tail: c.tail ?? "",
}));

log(`commits on ${cfg.branch}: ${summary.commits.length}`);
if (allChecks.length === 0) {
  log(
    (cfg.checks ?? []).length === 0
      ? "deterministic checks: none were configured (pass --check)"
      : "deterministic checks: configured, but the run stopped before they could run",
  );
} else if (summary.checksPassed) {
  log(
    `deterministic checks: all ${allChecks.length} passed` +
      (summary.fixRounds > 0 ? ` (after ${summary.fixRounds} repair round(s))` : ""),
  );
} else {
  log(`deterministic checks: ${failedChecks.length} of ${allChecks.length} FAILED`);
  for (const c of failedChecks) log(`  failed: ${c.command} (exit ${c.exitCode})`);
}

process.stdout.write(
  `\n===AGENTBOX_SUMMARY_JSON===\n${JSON.stringify(summary, null, 2)}\n===END===\n`,
);

process.exit(exitCode);
