// Dependency-free contracts: node --test tests/dash/duration.test.js
import assert from "node:assert/strict";
import test from "node:test";
import { elapsedDuration, quietDuration, receiveDuration } from "../../src/taskloop/dash/static/duration.js";
import { elapsedSpan, quietSpan, tick } from "../../src/taskloop/dash/static/ui.js";

const sample = (execution, extra = {}) => ({
  execution, number: 1, elapsed_ms: 119999, quiet_ms: 119999, frozen: false, ...extra,
});

test("live measurements share progress across wall jumps, reordered receipts and executions", (t) => {
  let now = 1000;
  t.mock.method(performance, "now", () => now);
  const first = sample("receipts");
  receiveDuration(first);
  now += 1001;
  for (const wall of [0, 9000000000000]) {
    t.mock.method(Date, "now", () => wall);
    receiveDuration(first);
    receiveDuration({ ...first, number: 0, elapsed_ms: 0 });
    assert.equal(elapsedDuration(first.execution), 121000);
    assert.equal(quietDuration(first.execution), 121000);
  }
  receiveDuration({ ...first, number: 2, elapsed_ms: 120000, quiet_ms: 120000 });
  now += 1000;
  assert.equal(elapsedDuration(first.execution), 122000);
  assert.equal(quietDuration(first.execution), 122000);
  receiveDuration({ ...first, number: 3, elapsed_ms: 121000, quiet_ms: 1000 });
  assert.equal(elapsedDuration(first.execution), 122000);
  assert.equal(quietDuration(first.execution), 1000);
  receiveDuration(first);
  receiveDuration(null);
  now += 1000;
  assert.equal(quietDuration(first.execution), 2000);
  receiveDuration(sample("next", { elapsed_ms: 3000, quiet_ms: 0 }));
  assert.equal(elapsedDuration("next"), 3000);
  assert.equal(elapsedDuration(first.execution), 123000);
});

test("quiet presentation retains exact thresholds and clears card severity on new command evidence", (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const card = { dataset: {} };
  // Only the DOM operations used by the shared presentation helpers; integration uses the HTML fixtures.
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({
    dataset: {}, closest: () => card,
    replaceChildren(...children) { this.children = children; },
  }) };
  try {
    const first = sample("thresholds");
    receiveDuration(first);
    const quiet = quietSpan(first);
    const elapsed = elapsedSpan(first, "", "", " in step");
    assert.equal(quiet.hidden, true);
    assert.equal(card.dataset.quietLevel, "");
    now = 1; tick(quiet); tick(elapsed);
    assert.equal(elapsed.textContent, "2m 00s in step");
    assert.equal(quiet.hidden, false);
    assert.equal(quiet.children[0].className.includes("bg-amber-500"), true);
    assert.equal(quiet.children[1], "Last activity 2m 00s ago");
    now = 780000; tick(quiet);
    assert.equal(card.dataset.quietLevel, "slow");
    now = 780001; tick(quiet);
    assert.equal(card.dataset.quietLevel, "long");
    assert.equal(quiet.children[0].className.includes("bg-rose-500"), true);
    assert.equal(quiet.children[1], "Last activity 15m 00s ago");
    receiveDuration({ ...first, number: 2, elapsed_ms: 900000, quiet_ms: 0 });
    tick(quiet);
    assert.equal(quiet.hidden, true);
    assert.equal(card.dataset.quietLevel, "");
    assert.equal(elapsedSpan(first).textContent, "15m 00s");
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  }
});

test("sealed input does not advance or accept a later live receipt", (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  receiveDuration(sample("sealed", { frozen: true, elapsed_ms: 3000, quiet_ms: null }));
  now = 900000;
  receiveDuration(sample("sealed", { number: 2 }));
  assert.equal(elapsedDuration("sealed"), 3000);
  assert.equal(quietDuration("sealed"), null);
});

test("final elapsed replaces extrapolation and survives ticks, reordering and a fresh module", async (t) => {
  let now = 0;
  t.mock.method(performance, "now", () => now);
  const live = sample("final");
  receiveDuration(live);
  now = 900000;
  assert.equal(elapsedDuration(live.execution), 1019999);
  const final = { ...live, number: 2, elapsed_ms: 3000, quiet_ms: null, frozen: true };
  receiveDuration(final);
  for (const receipt of [live, final, { ...live, number: 3 }]) {
    now += 86400000;
    receiveDuration(receipt);
    assert.equal(elapsedDuration(final.execution), 3000);
    assert.equal(quietDuration(final.execution), null);
  }
  const fresh = await import("../../src/taskloop/dash/static/duration.js?terminal-refresh");
  fresh.receiveDuration(final);
  now += 86400000;
  assert.equal(fresh.elapsedDuration(final.execution), 3000);
});

test("unknown presentation is explicit and neutral, while zero and frozen elapsed remain known", (t) => {
  t.mock.method(performance, "now", () => 0);
  const card = { dataset: {} };
  const previous = globalThis.document;
  globalThis.document = { createElement: () => ({
    dataset: {}, closest: () => card,
    replaceChildren(...children) { this.children = children; this.textContent = children.join(""); },
  }) };
  try {
    const first = sample("availability", { elapsed_ms: 900000, quiet_ms: 900000 });
    receiveDuration(first);
    const quiet = quietSpan(first);
    assert.equal(card.dataset.quietLevel, "long");
    receiveDuration({ ...first, number: 2, quiet_ms: null });
    tick(quiet);
    assert.equal(quiet.textContent, "Last activity unknown");
    assert.equal(quiet.hidden, false);
    assert.equal(quiet.children.length, 1);
    assert.equal(/amber|rose/.test(quiet.className), false);
    assert.equal(card.dataset.quietLevel, "");
    const unknown = elapsedSpan(null, "", "ran ", " in step");
    assert.equal(unknown.textContent, "Unknown duration");
    assert.equal(unknown.dataset.duration, undefined);
    assert.equal(quietSpan(null).textContent, "Last activity unknown");
    receiveDuration({ ...first, number: 3, quiet_ms: 900000 });
    tick(quiet);
    assert.equal(card.dataset.quietLevel, "long");
    const final = sample("zero-final", { frozen: true, elapsed_ms: 0, quiet_ms: null });
    receiveDuration(final);
    const elapsed = elapsedSpan(final, "", "ran ");
    tick(elapsed);
    assert.equal(elapsed.textContent, "ran 0ms");
    assert.equal(quietSpan(final).hidden, true);
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  }
});
