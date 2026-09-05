// clone-integrity.mjs - the defense-in-depth snapshot of a disposable clone.
//
// bin/agentbox owns the boundary: the real repository is never mounted, and
// the host validates every commit before it imports one. This module adds the
// second, cheaper signal. It records what the DISPOSABLE clone's refs, HEAD,
// local configuration and hooks were before the sandbox existed, and compares
// them after it is destroyed, so a run that wrote outside its own branch says
// so out loud even though the write could not leave the run directory.
//
// It lives in its own file so that the comparison can be exercised directly,
// with no container and no model credential. verify/probes/clone-integrity.test.mjs
// is what proves each rule below still holds.
//
// bin/agentbox stages this file next to orchestrate.mjs and mounts both into
// /opt/workstation/sandcastle, where the Sandcastle dependency tree lives.

import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";

/** git in <repo>, trimmed. A non-zero exit throws. */
export const git = (repo, args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();

/** git(), but a non-zero exit yields "" instead of throwing.
 *  "symbolic-ref HEAD" exits 1 on a detached HEAD and "config --list" exits 1
 *  when there is no local config file. Both are valid states to record. */
export const gitOrEmpty = (repo, args) => {
  try {
    return git(repo, args);
  } catch {
    return "";
  }
};

/** The absolute path of the git directory shared by every worktree. */
export const gitCommonDir = (repo) =>
  git(repo, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);

/** A sorted list of "<name> <mode> <size>" for the hook directory.
 *  The .sample files git ships are not hooks: git never runs them. */
export const hookInventory = (commonDir) => {
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
      return `${e.name} ${(st.mode & 0o7777).toString(8)} ${st.size}`;
    })
    .sort();
};

/**
 * Everything about <repo> that a run must leave alone.
 *
 * The configuration is read with "config --local --list", so it is the clone's
 * own file and nothing the surrounding environment contributes. Every entry is
 * compared verbatim: agentbox deliberately has no allow-list of keys an agent
 * may change, because every git configuration key is either a command the host
 * would run or a rule the host would trust.
 */
export const snapshotIntegrity = (repo) => {
  const commonDir = gitCommonDir(repo);
  return {
    commonDir,
    refs: git(repo, ["for-each-ref", "--format=%(refname) %(objectname)"])
      .split("\n")
      .filter(Boolean)
      .sort(),
    head: gitOrEmpty(repo, ["symbolic-ref", "--quiet", "HEAD"]),
    config: gitOrEmpty(repo, ["config", "--local", "--list"])
      .split("\n")
      .filter(Boolean)
      .sort(),
    hooks: hookInventory(commonDir),
  };
};

/**
 * One line per difference between two snapshots. An empty array means the run
 * stayed inside the one branch it was given.
 *
 * agentRef is the single refname the run is allowed to create or move.
 * Everything else - any other ref, the checked-out branch, any configuration
 * entry, any hook - is a violation in both directions.
 */
export const diffIntegrity = (before, after, agentRef) => {
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

/**
 * The configuration lines a baseline must already carry for the run to be
 * allowed to start.
 *
 * bin/agentbox gives every disposable clone a neutral identity at clone time.
 * Sandcastle copies user.name and user.email out of the clone into the sandbox
 * as part of run(), so the agent CLI finds an identity and does not write one
 * of its own halfway through the run. An identity that is missing here means
 * the clone was not prepared the way this program expects, and the run must
 * stop rather than fail later at the integrity comparison.
 *
 * Returns one line per missing entry; an empty array means the baseline is the
 * expected one.
 */
export const missingIdentity = (config, identity) => {
  const want = [`user.name=${identity?.name ?? ""}`, `user.email=${identity?.email ?? ""}`];
  return want.filter((line) => !config.includes(line));
};

/**
 * What a worktree still has uncommitted, one porcelain line per entry.
 *
 * Sandcastle removes the worktree it made when the worktree is clean, and
 * PRESERVES it when it is not. Preserving is the safe half of that choice and
 * must stay: a worktree that still holds work is evidence, and an orchestrator
 * that deleted one to quieten its own warning would destroy the only copy.
 *
 * The message alone is not enough to act on. bin/agentbox removes the whole
 * run directory when a run succeeds, so the path the message names is gone
 * before a human reads the log, and "uncommitted changes" never says whether
 * that was one generated lockfile or a repository the run left broken.
 * Reading the status here, while the worktree still exists, is what makes the
 * answer survive the run.
 *
 * The untracked mode is deliberately "normal": an untracked directory
 * collapses to one entry, so a package manager that wrote 18448 files reports
 * one line rather than 18448.
 *
 * An empty array is not an error. It is what a preserved worktree looks like
 * once the state that made it dirty is gone. A worktree git cannot read at all
 * is a different answer, so this throws rather than reporting it as clean.
 *
 * git() is deliberately NOT used. Porcelain status is two columns wide, and a
 * file that is modified but not staged reports a LEADING space (" M path").
 * Trimming the output would eat that column on the first line only, so the
 * same state would read differently depending on its position in the list.
 */
export const worktreeStatus = (worktree) =>
  execFileSync(
    "git",
    ["-C", worktree, "status", "--porcelain", "--untracked-files=normal"],
    { encoding: "utf8" },
  )
    .split("\n")
    .filter(Boolean);

/** How many status lines a preserved-worktree report prints before it counts
 *  the rest. A run that left a whole dependency tree untracked must still
 *  produce a report a human reads, not one they scroll past. */
export const PRESERVED_STATUS_LIMIT = 20;

/**
 * The indented body of the preserved-worktree report, one string per line.
 *
 * Kept beside worktreeStatus, and separate from the orchestrator, so that the
 * bound and the empty case can both be proved with no container and no model
 * credential. The caller adds the "[agentbox]" prefix.
 */
export const preservedWorktreeLines = (entries, limit = PRESERVED_STATUS_LIMIT) => {
  if (entries.length === 0) return ["  the worktree reports nothing uncommitted now"];
  const lines = entries.slice(0, limit).map((e) => `  ${e}`);
  if (entries.length > limit) {
    lines.push(`  ... and ${entries.length - limit} more`);
  }
  return lines;
};
