// budget.test.mjs - the execution-efficiency budget, proved with an injected
// clock and an injected counter, so no test here waits a real minute.
//
//   node --test verify/probes/
//
// verify/80-sandcastle.sh runs this.
//
// What these tests exist to hold in place:
//
//   * a soft threshold warns once and does NOT stop the invocation
//   * a hard threshold stops it, and stops it only once
//   * the wall-clock limit fires with NO tool call at all, which is the case
//     an idle timeout cannot see: an agent that keeps talking and gets nowhere
//   * a completion before either limit consumes no budget
//   * each invocation is measured on its own, so a repair does not inherit the
//     implementation's counters
//   * a soft limit at or above its hard limit is refused, not clamped
//   * absent token usage stays absent, and never becomes a zero

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  budgetIsOff,
  createBudgetMeter,
  describeBreach,
  evaluateBudget,
  normalizeBudget,
  NO_BUDGET,
  sumTokenUsage,
} from "../../config/sandcastle/budget.mjs";

/** A clock the test moves by hand. */
const fakeClock = () => {
  let ms = 1_000_000;
  const now = () => ms;
  now.advanceSeconds = (seconds) => {
    ms += seconds * 1000;
  };
  return now;
};

const BUDGET = {
  softSeconds: 600,
  hardSeconds: 1200,
  softToolCalls: 30,
  hardToolCalls: 60,
};

const meterFor = (budget = BUDGET) => {
  const now = fakeClock();
  const warnings = [];
  const breaches = [];
  const meter = createBudgetMeter({
    budget,
    now,
    onWarn: (w) => warnings.push(w),
    onExceed: (b) => breaches.push(b),
  });
  return { meter, now, warnings, breaches };
};

const callTools = (meter, count) => {
  for (let i = 0; i < count; i += 1) meter.countToolCall();
};

describe("normalizeBudget", () => {
  it("reads the four limits and treats an absent one as off", () => {
    assert.deepEqual(normalizeBudget({ softSeconds: 10, hardSeconds: 20 }), {
      ...NO_BUDGET,
      softSeconds: 10,
      hardSeconds: 20,
    });
    assert.equal(budgetIsOff(normalizeBudget({})), true);
    assert.equal(budgetIsOff(normalizeBudget(undefined)), true);
    assert.equal(budgetIsOff(normalizeBudget(BUDGET)), false);
  });

  it("refuses a soft limit that is not below its hard limit", () => {
    assert.throws(
      () => normalizeBudget({ softSeconds: 600, hardSeconds: 600 }),
      /softSeconds \(600\) must be below hardSeconds \(600\)/,
    );
    assert.throws(
      () => normalizeBudget({ softToolCalls: 90, hardToolCalls: 60 }),
      /softToolCalls/,
    );
  });

  it("refuses a limit that is not a whole number of zero or more", () => {
    assert.throws(() => normalizeBudget({ hardSeconds: -1 }), /whole number/);
    assert.throws(() => normalizeBudget({ hardSeconds: 1.5 }), /whole number/);
    assert.throws(() => normalizeBudget({ hardSeconds: "600" }), /whole number/);
  });

  it("allows a hard limit with no soft limit in front of it", () => {
    assert.equal(normalizeBudget({ hardToolCalls: 60 }).softToolCalls, 0);
  });
});

describe("evaluateBudget", () => {
  it("reports ok below every limit", () => {
    const verdict = evaluateBudget({ seconds: 599, toolCalls: 29 }, BUDGET);
    assert.equal(verdict.level, "ok");
    assert.deepEqual(verdict.breaches, []);
  });

  it("reports the hard level when one metric is hard and another is soft", () => {
    const verdict = evaluateBudget({ seconds: 1200, toolCalls: 31 }, BUDGET);
    assert.equal(verdict.level, "hard");
    assert.deepEqual(
      verdict.breaches.map((b) => b.metric),
      ["seconds"],
    );
  });

  it("names every metric that reached the level it reports", () => {
    const verdict = evaluateBudget({ seconds: 1300, toolCalls: 61 }, BUDGET);
    assert.equal(verdict.level, "hard");
    assert.deepEqual(
      verdict.breaches.map((b) => b.metric),
      ["seconds", "toolCalls"],
    );
  });

  it("bounds nothing when the limit is zero", () => {
    const verdict = evaluateBudget({ seconds: 99999, toolCalls: 99999 }, NO_BUDGET);
    assert.equal(verdict.level, "ok");
  });

  it("renders a breach as a line naming the value and the limit", () => {
    assert.match(
      describeBreach({ metric: "seconds", level: "hard", limit: 1200, value: 1300 }),
      /1300s of model time \(hard limit 1200s\)/,
    );
    assert.match(
      describeBreach({ metric: "toolCalls", level: "soft", limit: 30, value: 31 }),
      /31 tool calls \(soft limit 30\)/,
    );
  });
});

describe("the meter, on a normal invocation", () => {
  it("consumes no budget when the agent finishes early", () => {
    const { meter, now, warnings, breaches } = meterFor();
    meter.begin("implement");
    callTools(meter, 12);
    now.advanceSeconds(300);
    meter.tick();
    const record = meter.end();

    assert.deepEqual(warnings, []);
    assert.deepEqual(breaches, []);
    assert.equal(meter.exceeded, null);
    assert.equal(record.toolCalls, 12);
    assert.equal(record.seconds, 300);
    assert.equal(meter.snapshot().invocations, 1);
  });
});

describe("the soft threshold", () => {
  it("warns on the tool count and lets the invocation continue", () => {
    const { meter, warnings, breaches } = meterFor();
    meter.begin("implement");
    callTools(meter, 31);

    assert.equal(warnings.length, 1);
    assert.equal(warnings[0].phase, "implement");
    assert.deepEqual(
      warnings[0].breaches.map((b) => b.metric),
      ["toolCalls"],
    );
    assert.deepEqual(breaches, []);
    assert.equal(meter.exceeded, null);
  });

  it("warns once per invocation, not once per tool call", () => {
    const { meter, warnings } = meterFor();
    meter.begin("implement");
    callTools(meter, 45);
    assert.equal(warnings.length, 1);
  });

  it("warns again in the next invocation, which has its own counters", () => {
    const { meter, warnings } = meterFor();
    meter.begin("implement");
    callTools(meter, 31);
    meter.end();

    meter.begin("fix-1");
    callTools(meter, 31);
    assert.equal(warnings.length, 2);
    assert.deepEqual(
      warnings.map((w) => w.phase),
      ["implement", "fix-1"],
    );
    // The repair inherited nothing: it warned at its own 30th call, which is
    // the limit, not at the run's 31st.
    assert.equal(warnings[0].toolCalls, 30);
    assert.equal(warnings[1].toolCalls, 30);
    assert.equal(meter.snapshot().toolCalls, 62);
  });

  it("keeps the warning in the run record", () => {
    const { meter } = meterFor();
    meter.begin("implement");
    callTools(meter, 31);
    meter.end();
    const snapshot = meter.snapshot();
    assert.equal(snapshot.warnings.length, 1);
    assert.equal(snapshot.phases[0].warned, true);
    assert.equal(snapshot.exceeded, null);
  });
});

describe("the hard threshold", () => {
  it("stops the invocation on the tool count", () => {
    const { meter, breaches } = meterFor();
    meter.begin("implement");
    callTools(meter, 60);

    assert.equal(breaches.length, 1);
    assert.equal(breaches[0].phase, "implement");
    assert.equal(breaches[0].toolCalls, 60);
    assert.ok(meter.exceeded);
  });

  it("stops once, and stays stopped for the rest of the run", () => {
    const { meter, breaches } = meterFor();
    meter.begin("implement");
    callTools(meter, 90);
    meter.end();
    meter.begin("fix-1");
    callTools(meter, 90);

    assert.equal(breaches.length, 1);
    assert.equal(breaches[0].phase, "implement");
  });

  it("fires on wall-clock time with no tool call at all", () => {
    // The case an idle timeout cannot see. The agent produces output the whole
    // time, so it is never idle, and it calls no tool, so no counter moves.
    const { meter, now, breaches } = meterFor();
    meter.begin("implement");
    now.advanceSeconds(1200);
    meter.tick();

    assert.equal(breaches.length, 1);
    assert.deepEqual(
      breaches[0].breaches.map((b) => b.metric),
      ["seconds"],
    );
    assert.equal(breaches[0].toolCalls, 0);
  });

  it("passes the soft stage first when time crosses both", () => {
    const { meter, now, warnings, breaches } = meterFor();
    meter.begin("implement");
    now.advanceSeconds(700);
    meter.tick();
    assert.equal(warnings.length, 1);
    assert.equal(breaches.length, 0);

    now.advanceSeconds(600);
    meter.tick();
    assert.equal(breaches.length, 1);
  });

  it("keeps the breach in the run record, with what it cost", () => {
    const { meter, now } = meterFor();
    meter.begin("implement");
    callTools(meter, 60);
    now.advanceSeconds(30);
    meter.end();

    const snapshot = meter.snapshot();
    assert.ok(snapshot.exceeded);
    assert.equal(snapshot.exceeded.phase, "implement");
    assert.equal(snapshot.toolCalls, 60);
    assert.equal(snapshot.invocations, 1);
    assert.deepEqual(snapshot.limits, BUDGET);
  });

  it("bounds nothing when every limit is off", () => {
    const { meter, now, warnings, breaches } = meterFor(NO_BUDGET);
    meter.begin("implement");
    callTools(meter, 500);
    now.advanceSeconds(100_000);
    meter.tick();

    assert.deepEqual(warnings, []);
    assert.deepEqual(breaches, []);
    assert.equal(meter.exceeded, null);
  });
});

describe("token usage", () => {
  it("sums what the provider reported", () => {
    assert.deepEqual(
      sumTokenUsage([
        { usage: { inputTokens: 10, outputTokens: 2 } },
        { usage: { input_tokens: 5, output_tokens: 1 } },
      ]),
      { inputTokens: 15, outputTokens: 3 },
    );
  });

  it("stays absent when the provider reported nothing", () => {
    assert.equal(sumTokenUsage([{}, { usage: null }]), null);
    assert.equal(sumTokenUsage([]), null);
    assert.equal(sumTokenUsage(undefined), null);
  });

  it("accumulates across invocations in the meter", () => {
    const { meter } = meterFor();
    meter.begin("implement");
    meter.addUsage([{ usage: { inputTokens: 10, outputTokens: 2 } }]);
    meter.end();
    meter.begin("fix-1");
    meter.addUsage([{ usage: { inputTokens: 4, outputTokens: 1 } }]);
    meter.end();

    assert.deepEqual(meter.snapshot().tokens, { inputTokens: 14, outputTokens: 3 });
  });

  it("reports no tokens rather than zero tokens when none were measured", () => {
    const { meter } = meterFor();
    meter.begin("implement");
    meter.addUsage([{}]);
    meter.end();
    assert.equal(meter.snapshot().tokens, null);
  });
});
