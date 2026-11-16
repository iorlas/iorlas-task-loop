// Serve navigation.html, or use Chromium's --allow-file-access-from-files. Only fake data is read.
import { decode, encode, initNavigation, ROUTE } from "../../src/taskloop/dash/static/navigation.js";
import { closeDrawer, initDrawer, onTaskMoved, openDrawer } from "../../src/taskloop/dash/static/drawer.js";
import { initLogs, loadLogs } from "../../src/taskloop/dash/static/logs.js";
import { activateCard } from "../../src/taskloop/dash/static/accessibility.js";

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
async function until(test, message) {
  for (let i = 0; i < 100; i++) {
    if (test()) return;
    await tick();
  }
  throw new Error(message);
}
const drawer = document.getElementById("drawer");
const tab = (id) => drawer.querySelector(`#${id}`);
const click = async (id) => { assert(tab(id), `Missing ${id}`); tab(id).click(); await tick(); };
const selected = (id) => tab(id)?.getAttribute("aria-selected") === "true";
const hidden = () => drawer.classList.contains("translate-x-full");
const attempt = (step, n, extra = {}) => ({ step, n, state: "succeeded", summary: "passed", feed: [], ...extra });
const card = (id) => ({ id, title: `Title ${id}`, column: "implement", attempt: 2 });
const rows = () => [
  attempt("plan", 1, { past: true }), attempt("commit", 31, { past: true }),
  attempt("implement", 1, { past: true }), attempt("commit", 32, { past: true }),
  attempt("checks", 1, { past: true }),
  attempt("plan", 2, { after: "restart_at_plan" }), attempt("commit", 33),
  attempt("implement", 2, { after: "repeat", repeat_of: 1, led_by: 32, state: "running" }),
];
let detailCalls = 0;
let detailRead = async (id) => {
  if (id === "missing") throw new Error("No such task");
  return { task: card(id), attempts: id === "empty" ? [] : rows() };
};
const source = {
  detail: (id) => { detailCalls++; return detailRead(id); },
  tracker: async () => { throw Object.assign(new Error("No tracker"), { status: 404 }); },
  body: async () => ({ input: "Prompt text", added: [], result: { summary: "passed", checks: [] } }),
  feed: async () => ({ events: [], cursor: "0:0" }),
  delivery: async () => ({ actions: ["Finish delivery"], summary: [], diff_files: 0, added: 0, deleted: 0 }),
  logs: async () => ({ rows: [{ task: "from-log", at: "2026-11-15T10:00:00Z", move: "implement", words: [] }] }),
};
const tasks = new Map(); // Direct URLs must work without a board card.
const applyRoute = (route) => route.kind === ROUTE.closed ? closeDrawer(true) : openDrawer(route.id, route);
let navigation = initNavigation(applyRoute);
initDrawer(source, tasks, (...args) => navigation.changed(...args));
initLogs(openDrawer);
activateCard(document.getElementById("card"), () => openDrawer("from-card"));

async function visit(hash) {
  if (location.hash === hash) return;
  location.hash = hash;
  await until(() => location.hash === hash && !drawer.textContent.includes("Loading the task's steps"), `Visit ${hash}`);
  await tick(); await tick();
}
async function travel(direction, hash) {
  history[direction]();
  await until(() => location.hash === hash, `${direction} to ${hash}`);
  await tick(); await tick();
}

function codec() {
  for (const hash of ["#tl-a/plan/1/lines", "#a%2Fb%20%23/implement/2/prompt", "#a/checks/3/result",
    "#a/commit/32/result", "#a/implement/2/task", "#a/task", "#a/land", "#a/land/task", "#a"]) {
    assert(encode(decode(hash)) === hash, `Roundtrip ${hash}`);
  }
  for (const hash of ["", "#", "#%zz", "#/plan/1/result", "#a/nonsense/1/result", "#a/plan/0/result",
    "#a/plan/-1/result", "#a/plan/1.5/result", "#a/plan/01/result", "#a/plan/9007199254740992/result",
    "#a/plan/1/nonsense", "#a/plan/1/result/extra", "#a/plan/1", "#a/land/1/result"]) {
    assert(decode(hash).kind === ROUTE.closed, `Reject ${hash}`);
  }
}

async function openingAndTabs() {
  closeDrawer();
  const before = history.length;
  document.getElementById("card").click(); await tick(); await tick();
  assert(location.hash === "#from-card/implement/2/lines", "Card opening resolves its default in the same entry");
  assert(history.length === before + 1, "Card creates exactly one entry");
  assert(tab("drawer-view-tab-attempts").textContent === "Steps 5", "Count includes past, repeated and check rows only");
  for (const name of ["result", "prompt", "lines"]) {
    await click(`attempt-body-tab-${name}`);
    assert(location.hash === `#from-card/implement/2/${name}`, `${name} updates URL`);
  }
  await click("drawer-view-tab-task");
  assert(location.hash === "#from-card/implement/2/task", "Task view retains identity");
  await travel("back", "#from-card/implement/2/lines");
  assert(selected("attempt-body-tab-lines"), "Back restores output tab");
  await travel("forward", "#from-card/implement/2/task");
  assert(selected("drawer-view-tab-task"), "Forward restores Task view");
  await loadLogs(source);
  [...document.querySelectorAll("#logs button")].find((b) => b.textContent === "from-log").click();
  await tick(); await tick();
  assert(location.hash === "#from-log/implement/2/lines", "Log opening uses the same navigation");
  const calls = detailCalls;
  await visit("#from-log/plan/1/prompt");
  assert(detailCalls === calls && selected("attempt-body-tab-prompt"), "Same-task URL reuses detail and restores past attempt");
  assert(drawer.querySelector("#rail details")?.open, "URL opens the selected past run");
  const rail = drawer.querySelector("#rail");
  [...rail.querySelectorAll("button")].find((b) => b.textContent.includes("Implementattempt 2")).click();
  assert(location.hash === "#from-log/implement/2/prompt", "Rail selection updates attempt identity");
  [...drawer.querySelectorAll("button")].find((b) => b.textContent.startsWith("because factory commit")).click();
  await tick();
  assert(location.hash === "#from-log/commit/32/result", "Cause link selects factory commit Result");
  assert(!tab("attempt-body-tab-prompt"), "Factory commit has no output tabs");
}

async function restorationAndClosure() {
  await visit("#a%2Fb%20%23/implement/1/prompt");
  assert(drawer.textContent.includes("Title a/b #"), "Encoded task loads without a card");
  assert(selected("attempt-body-tab-prompt"), "Direct URL restores tab");
  const calls = detailCalls;
  const length = history.length;
  navigation.stop(); closeDrawer(true);
  navigation = initNavigation(applyRoute);
  navigation.start(); await tick(); await tick();
  assert(detailCalls === calls + 1 && selected("attempt-body-tab-prompt"), "Fresh controller restores from URL");
  assert(history.length === length, "Restoration adds no entries");
  for (const close of [
    () => tab("drawer-close").click(),
    () => document.getElementById("backdrop").click(),
    () => drawer.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })),
  ]) {
    close(); await tick();
    assert(!location.hash && hidden(), "Dismissal closes URL and drawer");
    await travel("back", "#a%2Fb%20%23/implement/1/prompt");
    assert(!hidden() && selected("attempt-body-tab-prompt"), "Back restores dismissed drawer");
    await travel("forward", "");
    assert(hidden(), "Forward restores closure");
    await visit("#a%2Fb%20%23/implement/1/prompt");
  }
}

async function defaultsAndRepairs() {
  await visit("#empty/task");
  assert(selected("drawer-view-tab-task") && tab("drawer-view-tab-attempts").textContent === "Steps", "Empty task has plain Steps");
  await click("drawer-view-tab-attempts");
  assert(drawer.textContent.includes("Not started") && location.hash === "#empty/steps", "Empty Steps view has a restorable URL");
  await travel("back", "#empty/task");
  assert(selected("drawer-view-tab-task"), "Back restores empty Task view");
  await travel("forward", "#empty/steps");
  assert(selected("drawer-view-tab-attempts"), "Forward restores empty Steps view");
  await visit("#empty/land");
  assert(drawer.textContent.includes("Finish delivery"), "Delivery restores even without attempts");
  await visit("#direct/land");
  assert(drawer.textContent.includes("Finish delivery"), "Delivery URL restores pane");
  await click("drawer-view-tab-task");
  assert(location.hash === "#direct/land/task", "Task view retains delivery selection");
  await travel("back", "#direct/land");
  assert(drawer.textContent.includes("Finish delivery"), "Back restores delivery");
  await visit("#direct/commit/32/lines");
  assert(location.hash === "#direct/commit/32/result", "Factory commit URL repairs to Result");
  await visit("#direct/implement/999/result");
  assert(location.hash === "#direct/implement/2/lines", "Missing attempt falls back to task default");
  await visit("#defaults");
  assert(location.hash === "#defaults/implement/2/lines", "Bare task resolves default");
  await visit("#missing");
  assert(drawer.textContent.includes("No such task") && !hidden(), "Missing task retains error drawer");
  closeDrawer();
  await visit("#bad/plan/0/result");
  assert(!location.hash && hidden(), "Malformed URL repairs to closure");
}

async function staleReadsAndRefresh() {
  const original = detailRead;
  let finish;
  detailRead = (id) => id === "slow" ? new Promise((resolve) => { finish = resolve; }) : original(id);
  const pending = openDrawer("slow");
  await visit("#slow/plan/1/prompt");
  const count = history.length;
  finish(await original("slow")); await pending; await tick();
  assert(location.hash === "#slow/plan/1/prompt" && history.length === count, "Delayed detail uses newest same-task request");
  const closed = openDrawer("slow-close"); await closed;
  detailRead = () => new Promise((resolve) => { finish = resolve; });
  const late = openDrawer("late");
  closeDrawer();
  finish(await original("late")); await late;
  assert(!location.hash && hidden(), "Late detail cannot reopen closure");
  const old = openDrawer("old");
  const oldFinish = finish;
  detailRead = original;
  await openDrawer("new");
  oldFinish(await original("old")); await old;
  assert(location.hash.startsWith("#new/") && drawer.textContent.includes("Title new"), "Older task cannot overwrite newer task");
  const before = history.length;
  let refreshFinish;
  detailRead = () => new Promise((resolve) => { refreshFinish = resolve; });
  const refresh = onTaskMoved({ ...card("new"), attempt: 3 });
  await visit("#new/plan/1/prompt");
  refreshFinish(await original("new")); await refresh;
  assert(location.hash === "#new/plan/1/prompt", "Refresh preserves newer explicit selection");
  assert(history.length === before + 1, "Refresh and body redraws add no history");
  detailRead = async (id) => ({ task: card(id), attempts: [attempt("implement", 3)] });
  const currentLength = history.length;
  await onTaskMoved({ ...card("new"), attempt: 4 }); await tick();
  assert(location.hash === "#new/implement/3/result" && history.length === currentLength,
    "Refresh repairs removed selection with replacement");
  detailRead = original;
  closeDrawer();
}

try {
  codec();
  const reloadHash = sessionStorage.getItem("taskloop-navigation-reload");
  if (reloadHash) {
    sessionStorage.removeItem("taskloop-navigation-reload");
    navigation.start();
    await until(() => selected("drawer-view-tab-task"), "Reload restores Task tab");
    assert(location.hash === reloadHash, "Reload retains the selected attempt in the URL");
    await click("drawer-view-tab-attempts");
    assert(drawer.querySelector("section h3").textContent.includes("Implement, attempt 1"), "Reload restores past attempt identity");
    closeDrawer(); navigation.stop();
    document.getElementById("results").textContent = "PASS: navigation, reload, stale reads and Steps count, both themes";
  } else {
    history.replaceState(null, "", `${location.pathname}${location.search}`);
    navigation.start();
    for (const dark of [false, true]) {
      document.documentElement.classList.toggle("dark", dark);
      document.documentElement.classList.toggle("light", !dark);
      await openingAndTabs();
      await restorationAndClosure();
      await defaultsAndRepairs();
      await staleReadsAndRefresh();
    }
    const hash = "#reload/implement/1/task";
    await openDrawer("reload", decode(hash));
    sessionStorage.setItem("taskloop-navigation-reload", hash);
    location.reload();
  }
} catch (error) {
  closeDrawer(); navigation.stop();
  document.getElementById("results").textContent = `FAIL: ${error.stack}`;
}
