// budget.mjs - the execution-efficiency budget for one agentbox run.
//
// Sandcastle already stops an agent that says nothing (the idle timeout), an
// agent that signals completion but does not exit (the completion timeout),
// and a run that passes its wall-clock limit. None of those stops an agent
// that keeps talking. A model that explores for half an hour produces output
// on every turn, so every activity-based safeguard sees a healthy run.
//
// The budget is the missing limit. It measures WORK, not silence:
//
//     seconds     how long ONE model invocation has been running
//     tool calls  how many tools that invocation has used
//
// Two levels:
//
//     soft   the invocation is visibly expensive. Say so, and let it finish.
//     hard   the invocation is wasteful. Stop it, keep the evidence, and
//            import nothing.
//
// A hard breach is never a successful implementation. bin/agentbox exits 12,
// nothing is imported, and the coordinator classifies the issue as one that
// is probably too broad for a single bounded invocation.
//
// This file holds no input, no output and no clock of its own, so
// verify/probes/budget.test.mjs proves every threshold in milliseconds with an
// injected clock and an injected counter.

/** The metrics a budget bounds, in the order a breach reports them. */
export const BUDGET_METRICS = ["seconds", "toolCalls"];

/** Every limit is off. A zero limit means "do not bound this metric". */
export const NO_BUDGET = Object.freeze({
  softSeconds: 0,
  hardSeconds: 0,
  softToolCalls: 0,
  hardToolCalls: 0,
});

const LIMIT_KEYS = ["softSeconds", "hardSeconds", "softToolCalls", "hardToolCalls"];

class BudgetError extends Error {}

const whole = (value, key) => {
  if (value === undefined || value === null) return 0;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new BudgetError(`${key} must be a whole number of zero or more`);
  }
  return value;
};

/** Read one budget document, and refuse one that cannot be carried out.
 *
 * A soft limit at or above its hard limit is a configuration error, not a
 * value to clamp: it would mean the warning arrives after the stop, and an
 * operator who wrote it believes there is a warning stage when there is none.
 */
export const normalizeBudget = (raw) => {
  const budget = { ...NO_BUDGET };
  for (const key of LIMIT_KEYS) budget[key] = whole(raw?.[key], key);
  for (const [soft, hard] of [
    ["softSeconds", "hardSeconds"],
    ["softToolCalls", "hardToolCalls"],
  ]) {
    if (budget[hard] && budget[soft] && budget[soft] >= budget[hard]) {
      throw new BudgetError(
        `${soft} (${budget[soft]}) must be below ${hard} (${budget[hard]})`,
      );
    }
  }
  return Object.freeze(budget);
};

export const budgetIsOff = (budget) => LIMIT_KEYS.every((key) => !budget[key]);

/** Compare one invocation's state against the budget.
 *
 * Total, deterministic and free of side effects. ``level`` is the worst level
 * reached, and ``breaches`` names every metric at that level, so the message a
 * reader sees says which limit was passed and by how much.
 */
export const evaluateBudget = (state, budget) => {
  const seconds = Math.max(0, Math.floor(state?.seconds ?? 0));
  const toolCalls = Math.max(0, Math.floor(state?.toolCalls ?? 0));
  const value = { seconds, toolCalls };
  const breaches = [];
  for (const metric of BUDGET_METRICS) {
    const key = metric === "seconds" ? "Seconds" : "ToolCalls";
    const hard = budget[`hard${key}`];
    const soft = budget[`soft${key}`];
    if (hard && value[metric] >= hard) {
      breaches.push({ metric, level: "hard", limit: hard, value: value[metric] });
    } else if (soft && value[metric] >= soft) {
      breaches.push({ metric, level: "soft", limit: soft, value: value[metric] });
    }
  }
  const level = breaches.some((b) => b.level === "hard")
    ? "hard"
    : breaches.length > 0
      ? "soft"
      : "ok";
  return { level, breaches: breaches.filter((b) => b.level === level) };
};

/** One breach, as a line a human reads. */
export const describeBreach = (breach) =>
  breach.metric === "seconds"
    ? `${breach.value}s of model time (${breach.level} limit ${breach.limit}s)`
    : `${breach.value} tool calls (${breach.level} limit ${breach.limit})`;

/** Sum whatever token usage an agent result exposes.
 *
 * Sandcastle publishes per-iteration usage when the provider reports it, and
 * publishes nothing when the provider does not. Both are normal, so an absent
 * field is an absent number and never a zero that looks like a measurement.
 */
export const sumTokenUsage = (iterations) => {
  let input = 0;
  let output = 0;
  let seen = false;
  for (const iteration of iterations ?? []) {
    const usage = iteration?.usage;
    if (!usage || typeof usage !== "object") continue;
    const i = usage.inputTokens ?? usage.input_tokens ?? usage.promptTokens;
    const o = usage.outputTokens ?? usage.output_tokens ?? usage.completionTokens;
    if (typeof i === "number") {
      input += i;
      seen = true;
    }
    if (typeof o === "number") {
      output += o;
      seen = true;
    }
  }
  return seen ? { inputTokens: input, outputTokens: output } : null;
};

/** The meter one run keeps.
 *
 * It counts per invocation, because the invocation is the unit a budget
 * bounds, and it keeps run-wide totals for the summary. ``onWarn`` fires at
 * most once per invocation, and ``onExceed`` at most once per run: a limit
 * that reports itself on every tick would bury the line that matters.
 */
export const createBudgetMeter = ({
  budget,
  now = () => Date.now(),
  onWarn = () => {},
  onExceed = () => {},
} = {}) => {
  const limits = normalizeBudget(budget);
  const phases = [];
  let current = null;
  let toolCalls = 0;
  let invocations = 0;
  let tokens = null;
  let exceeded = null;
  const warnings = [];
  const startedAt = now();

  const phaseState = () =>
    current
      ? {
          seconds: Math.floor((now() - current.startedAt) / 1000),
          toolCalls: current.toolCalls,
        }
      : { seconds: 0, toolCalls: 0 };

  const tick = () => {
    if (!current || exceeded || budgetIsOff(limits)) return null;
    const state = phaseState();
    const verdict = evaluateBudget(state, limits);
    if (verdict.level === "hard") {
      exceeded = { phase: current.name, ...state, breaches: verdict.breaches };
      onExceed(exceeded);
      return exceeded;
    }
    if (verdict.level === "soft" && !current.warned) {
      current.warned = true;
      const warning = { phase: current.name, ...state, breaches: verdict.breaches };
      warnings.push(warning);
      onWarn(warning);
      return warning;
    }
    return null;
  };

  return {
    limits,

    /** Begin one model invocation. Every later count belongs to it. */
    begin(name) {
      invocations += 1;
      current = { name, startedAt: now(), toolCalls: 0, warned: false };
      return current;
    },

    /** End the invocation that is running, and keep its record. */
    end() {
      if (!current) return null;
      const record = {
        phase: current.name,
        ...phaseState(),
        warned: current.warned,
      };
      phases.push(record);
      current = null;
      return record;
    },

    /** One tool call the running invocation made. */
    countToolCall() {
      if (current) current.toolCalls += 1;
      toolCalls += 1;
      return tick();
    },

    /** Re-evaluate with no new work. The wall-clock limit needs this: an
     *  invocation that stops calling tools still spends time. */
    tick,

    /** Add the token usage of one finished invocation, when there is any. */
    addUsage(iterations) {
      const usage = sumTokenUsage(iterations);
      if (!usage) return null;
      tokens = {
        inputTokens: (tokens?.inputTokens ?? 0) + usage.inputTokens,
        outputTokens: (tokens?.outputTokens ?? 0) + usage.outputTokens,
      };
      return tokens;
    },

    get exceeded() {
      return exceeded;
    },

    /** The efficiency record the run summary carries. */
    snapshot() {
      return {
        limits: { ...limits },
        seconds: Math.floor((now() - startedAt) / 1000),
        invocations,
        toolCalls,
        tokens,
        phases: [...phases, ...(current ? [{ phase: current.name, ...phaseState(), warned: current.warned }] : [])],
        warnings: [...warnings],
        exceeded,
      };
    },
  };
};
