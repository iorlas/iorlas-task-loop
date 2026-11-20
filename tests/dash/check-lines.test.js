import { closeDrawer, initDrawer, onTaskMoved, openDrawer } from "../../src/taskloop/dash/static/drawer.js";

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const frame = () => new Promise(requestAnimationFrame);
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const task = { id: "live-checks", title: "Live checks", column: "checks", attempt: 1 };
const attempt = (n = 1, state = "running") => ({ step: "checks", n, state, summary: "Checks",
  started_at: null, ended_at: null, feed: [{ type: "check", name: "legacy", passed: false }] });
const event = (id, extra = {}) => ({ id, type: "check", at: "2026-11-15T10:00:00Z", block: 2,
  name: "lint", state: "running", passed: null, text: null, ...extra });
const page = (events = [], extra = {}) => ({ events, cursor: "opaque-one", available: true, replaced: false, ...extra });
const body = (checks = []) => ({ result: { summary: "Checks", checks } });
const check = (block, output = "output") => ({ block, name: "lint", passed: true, output, duration_ms: 10 });
const drawer = () => document.getElementById("drawer");
const rows = () => [...drawer().querySelectorAll("#lines [data-eid]")];
const row = (id) => rows().find((node) => node.dataset.eid === id);
const clickTab = (name) => drawer().querySelector(`#attempt-body-tab-${name}`).click();
const route = (n = 1) => ({ kind: "attempt", step: "checks", n, tab: "lines" });

async function fixture(run) {
  const interval = window.setInterval;
  let poll;
  let timers = 0;
  window.setInterval = (callback, ms) => {
    if (ms !== 2000) return interval(callback, ms);
    poll = callback; timers++; return 0;
  };
  try { await run(() => poll(), () => timers); }
  finally { closeDrawer(); window.setInterval = interval; }
}

export async function checkFollowing() {
  await fixture(async (poll, timers) => {
    let next = page([event("2:0:0", { text: "<script>Failure</script>\n  literal output" }), event("2:0:state")]);
    const calls = [];
    let failure = false;
    let pending;
    let detail = { task, attempts: [attempt()] };
    initDrawer({
      detail: async () => structuredClone(detail), tracker: async () => ({}), body: async () => body(),
      feed: async (...args) => {
        calls.push(args);
        if (pending) return pending.promise;
        if (failure) throw new Error("Offline");
        return structuredClone(next);
      },
    }, new Map([[task.id, task]]));
    await openDrawer(task.id, route()); await tick();
    assert(calls.length === 1 && calls[0][3] === undefined, "checks omit the initial cursor");
    assert(!drawer().textContent.includes("legacy") && rows().length === 2, "first page replaces legacy summaries");
    assert(row("2:0:0").textContent.includes("<script>Failure</script>\n  literal output"), "output stays literal");
    assert(!row("2:0:0").querySelector("script"), "output is never HTML");
    assert(row("2:0:state").textContent.includes("Running") && !row("2:0:state").textContent.includes("Failure"),
      "unknown outcome is neutral");
    next = page([event("2:0:state", { state: "finished", passed: true })], { cursor: "opaque-two" });
    await poll();
    assert(calls.at(-1)[3] === "opaque-one" && rows().length === 2, "follow opaque cursor and replace lifecycle row");
    assert(row("2:0:state").textContent.includes("Success"), "structured success");
    failure = true; await poll();
    assert(drawer().querySelector("#feednote").textContent.includes("Offline"), "transport failure is visible");
    failure = false; next = page([], { available: false }); await poll();
    assert(calls.at(-1)[3] === "opaque-two", "failure retains successful cursor");
    assert(drawer().querySelector("#feednote").textContent.includes("output unavailable"), "missing output differs from transport failure");
    next = page([event("3:0:state", { block: 3, state: "unfinished" })], { replaced: true }); await poll();
    assert(rows().length === 1 && row("3:0:state").textContent.includes("Unfinished"), "replacement removes obsolete output");
    next = page(Array.from({ length: 30 }, (_, i) => event(`3:0:${i}`, { text: `line ${i}` })));
    await poll();
    assert(rows().length === 20 && rows()[0].dataset.eid === "3:0:10", "live checks retain the bounded tail");
    next = page([], { replaced: true }); await poll();
    assert(!rows().length && drawer().textContent.includes("No lines recorded"), "empty replacement is understandable");
    pending = deferred();
    const flight = poll(); const count = calls.length;
    await poll(); assert(calls.length === count, "polls are serialized");
    closeDrawer();
    pending.resolve(page([event("late", { text: "CLOSED REPLY" })])); await flight;
    pending = null;
    assert(!drawer().textContent.includes("CLOSED REPLY"), "closed drawer ignores in-flight output");
    await openDrawer(task.id, route()); await tick();
    const before = timers();
    detail = { task: { ...task, column: "held" }, attempts: [attempt(1, "succeeded")] };
    next = page([event("final", { text: "terminal output", state: "finished", passed: true })]);
    failure = true;
    await onTaskMoved(detail.task); await tick();
    assert(drawer().querySelector("#feednote button"), "terminal transport failures offer retry");
    failure = false;
    drawer().querySelector("#feednote button").click(); await tick();
    assert(row("final") && timers() === before, "terminal refresh reads output once without polling");
    assert(calls.at(-1)[3] === undefined, "terminal refresh starts with a fresh check cursor");
  });
}

export async function checkActivation() {
  await fixture(async (poll) => {
    let next = page([event("target", { text: "passed output", state: "finished", passed: true })]);
    let pending = deferred();
    const routes = [];
    let reads = 0;
    initDrawer({
      detail: async () => ({ task, attempts: [attempt(1), attempt(2)] }), tracker: async () => ({}),
      feed: async () => structuredClone(next), body: async () => { reads++; return pending.promise; },
    }, new Map([[task.id, task]]), (selection) => routes.push(selection));
    await openDrawer(task.id, route()); await tick();
    clickTab("result");
    const stale = pending;
    clickTab("lines");
    pending = deferred();
    const button = row("target").querySelector("button");
    assert(button.type === "button" && button.getAttribute("aria-label").includes("block 2"), "semantic check activation");
    button.focus(); button.click();
    assert(routes.at(-1).step === "checks" && routes.at(-1).n === 1 && routes.at(-1).tab === "result",
      "activation reports Result navigation for the same attempt");
    assert(reads === 2 && drawer().textContent.includes("Loading"), "activation invalidates cached or pending bodies");
    pending.resolve(body([check(1, "other block"), check(2, "selected block")])); await tick(); await frame();
    let details = [...drawer().querySelectorAll("section details")];
    assert(!details[0].open && details[1].open, "passed check opens by block and name after body arrives");
    assert(details[1].contains(document.activeElement), "activated Result disclosure receives focus");
    stale.resolve(body([check(2, "STALE BODY")])); await tick();
    assert(!drawer().textContent.includes("STALE BODY"), "superseded body cannot overwrite refreshed output");
    details[1].open = false; await tick();
    clickTab("lines"); clickTab("result");
    details = [...drawer().querySelectorAll("section details")];
    assert(!details[1].open, "reveal is consumed so later disclosure choices survive");
    pending = deferred();
    next = page([event("fresh", { text: "fresh output" })]); await poll();
    assert(reads === 3 && drawer().textContent.includes("Loading"), "check changes refresh a cached running Result");
    pending.resolve(body([check(2, "fresh Result")])); await tick();
    assert(drawer().textContent.includes("fresh Result"), "running Result reads fresh evidence");
    clickTab("lines");
    pending = deferred();
    row("fresh").querySelector("button").click();
    await openDrawer(task.id, route(2)); await tick();
    pending.resolve(body([check(2, "OTHER ATTEMPT BODY")])); await tick(); await frame();
    assert(drawer().querySelector("section h3").textContent.includes("attempt 2") &&
      !drawer().textContent.includes("OTHER ATTEMPT BODY"), "late Result cannot navigate another attempt");
  });
}

export async function checkStaleFeed() {
  await fixture(async () => {
    const pending = deferred();
    const calls = [];
    initDrawer({
      detail: async () => ({ task, attempts: [attempt(1), attempt(2)] }), tracker: async () => ({}),
      body: async () => body(), feed: async (_id, _step, n, cursor) => {
        calls.push([n, cursor]);
        return n === 1 ? pending.promise : page([event("second", { text: "second attempt" })]);
      },
    }, new Map([[task.id, task]]));
    await openDrawer(task.id, route());
    await openDrawer(task.id, route(2)); await tick();
    pending.resolve(page([event("first", { text: "STALE FEED" })])); await tick();
    assert(row("second") && !row("first"), "switching attempts ignores late check pages");
    assert(calls.every(([, cursor]) => cursor === undefined), "every new checks selection starts without a cursor");
  });
}
