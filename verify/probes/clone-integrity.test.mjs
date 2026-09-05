// clone-integrity.test.mjs - the disposable-clone integrity comparison, proved
// against real Git repositories, with no container and no model credential.
//
//   node --test verify/probes/
//
// verify/80-sandcastle.sh runs this. Every test writes only inside a directory
// under the system temporary directory and removes it again.
//
// What these tests exist to hold in place:
//
//   * a clone prepared the way bin/agentbox prepares one carries the neutral
//     agent identity, and that identity is part of the baseline
//   * an unchanged identity is NOT a violation
//   * a LATER change to user.name or to user.email IS a violation
//   * every other configuration change an agent could make is still a
//     violation, including the executable ones: an alias, core.fsmonitor, a
//     pager, a clean filter, a credential helper
//
// The last group is the one that must never be weakened. The fix for the
// identity defect was to give the clone an identity, NOT to stop looking at
// user.name and user.email.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { after, describe, it } from "node:test";

import {
  diffIntegrity,
  missingIdentity,
  snapshotIntegrity,
} from "../../config/sandcastle/clone-integrity.mjs";

// The identity bin/agentbox sets. It is read from the manifest rather than
// repeated here, so this file cannot drift away from what a real run uses.
const manifest = execFileSync(
  "bash",
  [
    "-c",
    'set -eu; . "$1"; printf "%s\\n%s\\n" "$AGENTBOX_GIT_NAME" "$AGENTBOX_GIT_EMAIL"',
    "bash",
    fileURLToPath(new URL("../../manifests/sandcastle.env", import.meta.url)),
  ],
  { encoding: "utf8" },
).split("\n");
const IDENTITY = { name: manifest[0], email: manifest[1] };

const AGENT_BRANCH = "agent/probe";
const AGENT_REF = `refs/heads/${AGENT_BRANCH}`;

const scratch = mkdtempSync(join(tmpdir(), "agentbox-integrity-"));
after(() => rmSync(scratch, { recursive: true, force: true }));

let counter = 0;
const git = (repo, ...args) =>
  execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();

/** A repository prepared the way create_clone prepares a disposable clone:
 *  no remote, a base branch, and the neutral identity, set BEFORE anything
 *  records a baseline. */
const makeClone = () => {
  const repo = join(scratch, `clone-${counter++}`);
  mkdirSync(repo);
  git(repo, "init", "--quiet", "-b", "agentbox/base");
  git(repo, "config", "user.name", IDENTITY.name);
  git(repo, "config", "user.email", IDENTITY.email);
  writeFileSync(join(repo, "a.txt"), "one\n");
  git(repo, "add", "a.txt");
  git(repo, "commit", "--quiet", "-m", "first");
  return repo;
};

/** The violations a mutation produces, measured across a real baseline. */
const violationsAfter = (mutate) => {
  const repo = makeClone();
  const before = snapshotIntegrity(repo);
  mutate(repo);
  return { repo, before, violations: diffIntegrity(before, snapshotIntegrity(repo), AGENT_REF) };
};

describe("the prepared clone", () => {
  it("starts with the configured agent identity", () => {
    const repo = makeClone();
    assert.equal(git(repo, "config", "--local", "user.name"), IDENTITY.name);
    assert.equal(git(repo, "config", "--local", "user.email"), IDENTITY.email);
  });

  it("puts that identity in the integrity baseline", () => {
    const before = snapshotIntegrity(makeClone());
    assert.ok(before.config.includes(`user.name=${IDENTITY.name}`), before.config.join(" | "));
    assert.ok(before.config.includes(`user.email=${IDENTITY.email}`), before.config.join(" | "));
    assert.deepEqual(missingIdentity(before.config, IDENTITY), []);
  });

  it("is reported as unprepared when the identity is absent", () => {
    const repo = join(scratch, `bare-${counter++}`);
    mkdirSync(repo);
    git(repo, "init", "--quiet", "-b", "agentbox/base");
    const before = snapshotIntegrity(repo);
    assert.deepEqual(missingIdentity(before.config, IDENTITY), [
      `user.name=${IDENTITY.name}`,
      `user.email=${IDENTITY.email}`,
    ]);
  });
});

describe("an ordinary run", () => {
  it("produces no violation when nothing outside the agent branch changed", () => {
    const { violations } = violationsAfter(() => {});
    assert.deepEqual(violations, []);
  });

  it("produces no violation when the identity is left alone across a commit", () => {
    const { violations } = violationsAfter((repo) => {
      git(repo, "branch", AGENT_BRANCH);
      git(repo, "checkout", "--quiet", AGENT_BRANCH);
      writeFileSync(join(repo, "b.txt"), "two\n");
      git(repo, "add", "b.txt");
      git(repo, "commit", "--quiet", "-m", "the agent's work");
      git(repo, "checkout", "--quiet", "agentbox/base");
    });
    assert.deepEqual(violations, []);
  });
});

describe("a configuration change after the baseline", () => {
  it("is a violation when user.name is changed", () => {
    const { violations } = violationsAfter((repo) =>
      git(repo, "config", "user.name", "Claude"),
    );
    assert.ok(violations.includes("git config added: user.name=Claude"), violations.join(" | "));
    assert.ok(
      violations.includes(`git config removed: user.name=${IDENTITY.name}`),
      violations.join(" | "),
    );
  });

  it("is a violation when user.email is changed", () => {
    const { violations } = violationsAfter((repo) =>
      git(repo, "config", "user.email", "noreply@anthropic.com"),
    );
    assert.ok(
      violations.includes("git config added: user.email=noreply@anthropic.com"),
      violations.join(" | "),
    );
    assert.ok(
      violations.includes(`git config removed: user.email=${IDENTITY.email}`),
      violations.join(" | "),
    );
  });

  it("is a violation when a second user.name is added alongside the first", () => {
    const { violations } = violationsAfter((repo) =>
      git(repo, "config", "--add", "user.name", "Claude"),
    );
    assert.deepEqual(violations, ["git config added: user.name=Claude"]);
  });

  // Every entry below is host-side code or a host-side trust decision. None of
  // them may become tolerated as a side effect of tolerating an identity.
  for (const [what, key, value] of [
    ["an alias", "alias.pwn", "!touch /tmp/agentbox-pwned"],
    ["core.fsmonitor", "core.fsmonitor", "/tmp/agentbox-pwned"],
    ["a pager", "core.pager", "/tmp/agentbox-pwned"],
    ["an editor", "core.editor", "/tmp/agentbox-pwned"],
    ["a clean filter", "filter.pwn.clean", "/tmp/agentbox-pwned"],
    ["a credential helper", "credential.helper", "!/tmp/agentbox-pwned"],
    ["an uploadpack hook", "uploadpack.packObjectsHook", "/tmp/agentbox-pwned"],
    ["a hooks path", "core.hooksPath", "/tmp/agentbox-hooks"],
  ]) {
    it(`is a violation when ${what} is added`, () => {
      const { violations } = violationsAfter((repo) => git(repo, "config", key, value));
      // "git config --list" reports the section and the variable in lower
      // case; only a subsection keeps its spelling. The comparison is over
      // that normalised form, which is what makes it exact.
      assert.deepEqual(violations, [`git config added: ${key.toLowerCase()}=${value}`]);
    });
  }

  it("is a violation when an entry is removed", () => {
    const { violations } = violationsAfter((repo) =>
      git(repo, "config", "--unset", "user.email"),
    );
    assert.deepEqual(violations, [`git config removed: user.email=${IDENTITY.email}`]);
  });
});

describe("everything else the comparison covers", () => {
  it("is a violation when a hook is installed", () => {
    const { violations } = violationsAfter((repo) => {
      const hook = join(repo, ".git", "hooks", "post-checkout");
      writeFileSync(hook, "#!/bin/sh\ntouch /tmp/agentbox-pwned\n");
      chmodSync(hook, 0o755);
    });
    assert.equal(violations.length, 1);
    assert.match(violations[0], /^git hook added or changed: post-checkout /);
  });

  it("is a violation when an arbitrary ref is created", () => {
    const { violations } = violationsAfter((repo) =>
      git(repo, "update-ref", "refs/heads/agentbox-attacker", "HEAD"),
    );
    assert.equal(violations.length, 1);
    assert.match(violations[0], /^ref created or moved: refs\/heads\/agentbox-attacker /);
  });

  it("is a violation when the checked-out branch changes", () => {
    const { violations } = violationsAfter((repo) => {
      git(repo, "branch", "other");
      git(repo, "checkout", "--quiet", "other");
    });
    assert.ok(
      violations.some((v) => v.startsWith("the checked-out branch changed:")),
      violations.join(" | "),
    );
  });

  it("is not a violation when only the agent branch moves", () => {
    const { violations } = violationsAfter((repo) => {
      git(repo, "update-ref", AGENT_REF, "HEAD");
    });
    assert.deepEqual(violations, []);
  });
});
