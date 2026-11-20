import { closeDrawer, initDrawer, onTaskMoved, openDrawer } from "../../src/taskloop/dash/static/drawer.js";

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const drawer = () => document.getElementById("drawer");
const pane = () => drawer().querySelector("section.attempt-pane");
const attempt = (step, n, extra = {}) => ({ step, n, state: "failed", summary: "current summary",
  started_at: null, ended_at: null, feed: [], ...extra });
const context = (cause_id, cause) => ({ held_at: "2026-11-16T10:00:00Z",
  event: { attempt_id: cause_id === "checks" ? "agent" : cause_id, agent_step: "implement", cause_id,
    step: cause_id === "checks" ? "check" : "implement", cause } });
const landEvent = (id, n, past = true) => ({ id, kind: "tried", checks_id: "checks", checks_n: 1,
  candidate_id: `candidate-${n}`, candidate_n: n, at: "2026-11-16T10:00:00Z", past, explanation: `Saved candidate ${n}`,
  retry_cause: "moved", validation_started_at: "2026-11-16T10:00:10Z", validated_at: "2026-11-16T10:00:09Z", waits: [] });

export async function taskEvents() {
  const task = { id: "event-task", title: "Events", column: "land", land: "waiting", attempt: 1 };
  let events = [landEvent("one/tried", 1), landEvent("two/tried", 2, false)];
  const stored = context("checks", { family: "checks", check: { name: "lint", conclusion: "failed", log: "/log/<check>" },
    explanation: "Saved <img src=x onerror=bad> cause", checks: [{ name: "lint", conclusion: "failed", log: "/log/<check>" }] });
  const list = [attempt("plan", 1, { past: true, state: "succeeded" }),
  attempt("implement", 1, { past: true, context: context("agent", { family: "repeat",
    leftovers: { reason: "uncommitted", paths: ["src/<old>.py"] } }) }),
  attempt("checks", 1, { past: true, context: stored }),
  attempt("plan", 2, { state: "succeeded", after: "restart_at_plan", reason: "restarted at plan" }), attempt("implement", 2),
  attempt("implement", 3, { context: context("stopped", { family: "run", reason: "killed", rc: -15, timed_out: false,
    deadline: 120, stop: { attempt_id: "stopped", cause: "interrupt", dispatch_token: "dispatch", generation: 1,
      entry: { pid: 10, pgid: 10, start: "entry-start", boot: "boot" },
      agent: { pid: 11, pgid: 11, start: "agent-start", boot: "boot" },
      operation: "execute", requested_signal: 15, requested_at: 119, phase: "requested" } }) })];
  const routes = [], bodies = [];
  initDrawer({
    detail: async () => ({ task, attempts: list, land_events: events }),
    tracker: async () => ({ task: null, comments: [] }),
    body: async (_id, step, n) => { bodies.push(`${step}/${n}`); return { result: { summary: "body", checks: [] } }; },
    delivery: async () => ({ actions: ["Current actions"], summary: ["Current diff"], diff_files: null }),
  }, new Map([[task.id, task]]), (route) => routes.push(route));
  await openDrawer(task.id); await tick();
  assert(pane().textContent.includes("-15") && pane().textContent.includes("No") && pane().textContent.includes("interrupt"),
    "recorded exit, timeout and stop context retained");
  const history = drawer().querySelector("#rail details");
  history.open = true;
  const notice = drawer().querySelector('[data-task-event="checks"]');
  assert(notice.tagName === "BUTTON" && notice.type === "button", "cause has native keyboard activation");
  notice.focus();
  assert(document.activeElement === notice, "cause notice accepts keyboard focus");
  notice.click(); await tick();
  assert(drawer().querySelectorAll("section.attempt-pane").length === 1, "one detail panel");
  assert(pane().querySelector('[data-event-context="checks"]'), "checks owns its recorded cause");
  assert(pane().textContent.includes(stored.event.cause.explanation) && pane().textContent.includes("/log/<check>"),
    "snapshot and structured check context survive as text");
  assert(!drawer().querySelector("img"), "outside event text cannot create markup");
  assert(bodies.includes("checks/1") && routes.at(-1).step === "checks", "notice uses existing attempt endpoint and URL");
  drawer().querySelector('[data-task-event="agent"]').click(); await tick();
  assert(pane().textContent.includes("src/<old>.py"), "historical leftovers remain inspectable");
  const clickEvent = async (id) => { drawer().querySelector(`[data-land-event="${id}"] button`).click(); await tick(); };
  await clickEvent("one/tried");
  assert(pane().querySelector('[data-event-context="one/tried"]'), "first candidate selected independently");
  assert(pane().textContent.includes("Current delivery") && pane().textContent.includes("Current diff"),
    "live delivery reads clearly labelled beside history");
  assert(pane().textContent.includes("10:00:10Z") && pane().textContent.includes("10:00:09Z"),
    "recorded phase times retained despite clock disagreement");
  assert(drawer().querySelectorAll('[data-land-event] [aria-pressed="true"]').length === 1, "only chosen event pressed");
  assert(routes.at(-1).kind === "land" && !Object.hasOwn(routes.at(-1), "event"), "event selection stays local");
  await onTaskMoved({ ...task, status: "changed" }); await tick();
  assert(pane().querySelector('[data-event-context="one/tried"]'), "event retained across refresh");
  events = events.slice(1);
  await onTaskMoved({ ...task, status: "changed-again" }); await tick();
  assert(pane().querySelector('[data-event-context="two/tried"]'), "removed event defaults to latest survivor");
  drawer().querySelector('[data-task-event="checks"]').click(); await tick();
  assert(pane().querySelector('[data-event-context="checks"]'), "attempt selection clears land context");
  closeDrawer();
  await promptChanges();
  await promptChangeRaces();
}

const route = (n, tab = "lines", step = "implement") => ({ kind: "attempt", step, n, tab });
const comparison = (input = "Title\r\nAdded <img src=x>\u2028More\nKeep\n", added = [[1, 3]],
  base_before = "a".repeat(40), base_after = "b".repeat(40)) => ({
  input, added, change: { base_before, base_after }, result: { summary: "Saved result", checks: [] },
});
const changes = () => pane().querySelector("[data-what-changed]");
const tab = async (id) => { document.getElementById(`attempt-body-tab-${id}`).click(); await tick(); };

async function promptChanges() {
  const task = { id: "prompt-task", title: "Prompt changes", column: "held", attempt: 6 };
  const saved = context("repeat", { family: "repeat", leftovers: { reason: "uncommitted", paths: ["saved.py"] } });
  const list = [attempt("implement", 1), ...[2, 3, 4, 5, 6].map((n) => attempt("implement", n,
    { after: "repeat", repeat_of: n - 1, past: n === 2, context: saved })), attempt("checks", 1), attempt("commit", 1)];
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const calls = [];
  initDrawer({
    detail: async () => ({ task, attempts: list }), tracker: async () => ({}),
    body: async (_id, step, n) => {
      calls.push(`${step}/${n}`);
      if (step === "implement" && n === 2) return pending;
      if (n === 3) return comparison("Same", [], "a".repeat(40), "a".repeat(40));
      if (n === 4) return comparison("Same", [], null, "b".repeat(40));
      if (n === 5) return comparison("Same", [], null, null);
      if (n === 6) throw new Error("Missing <evidence>");
      return { input: "First prompt", added: [], change: null, result: { summary: "Saved result", checks: [] } };
    },
  }, new Map([[task.id, task]]));
  await openDrawer(task.id, route(2));
  assert(changes().textContent.includes("Loading changes") && pane().textContent.includes("saved.py"),
    "Lines loads changes while preserving the recorded cause");
  await tab("prompt"); await tab("result");
  assert(calls.length === 1, "all output tabs share the in-flight body request");
  finish(comparison()); await tick();
  assert(changes().textContent.includes("2 prompt lines added") && changes().textContent.includes("Added <img src=x>\nMore"),
    "historical repeat shows added/replaced text with the API's line boundaries");
  assert(!changes().textContent.includes("Title") && !changes().textContent.includes("Keep"), "changes omit retained prompt lines");
  assert(changes().textContent.includes(`${"a".repeat(40)} → ${"b".repeat(40)}`), "full recorded hashes shown old to new");
  assert(!pane().querySelector("img") && changes().parentElement === pane(), "changes are escaped and outside the output tabs");
  await tab("prompt");
  const marked = pane().querySelectorAll('[role="tabpanel"] .border-l-emerald-500');
  assert(marked.length === 2 && marked[0].textContent.includes("Added <img") && marked[1].textContent === "More",
    "complete prompt retains additions highlighted at the same line boundaries");
  await tab("lines");
  assert(changes().textContent.includes("2 prompt lines added") && calls.length === 1, "changes persist across all tabs without refetch");
  for (const [n, expected] of [[3, "(unchanged)"], [4, `unavailable → ${"b".repeat(40)}`], [5, "unavailable → unavailable"]]) {
    await openDrawer(task.id, route(n)); await tick();
    assert(changes().textContent.includes("0 prompt lines added") && changes().textContent.includes(expected),
      "identical prompts, equal bases and unavailable bases are explicit");
  }
  await openDrawer(task.id, route(1)); await tick();
  assert(changes().textContent.includes("No previous attempt to compare") && !changes().textContent.includes("0 prompt"),
    "unlinked attempt has no comparison");
  await openDrawer(task.id, route(6)); await tick();
  assert(changes().textContent.includes("Changes cannot be read: Missing <evidence>") && pane().textContent.includes("saved.py"),
    "unavailable evidence keeps the cause and tabs usable");
  await tab("prompt");
  assert(pane().textContent.includes("This attempt cannot be read"), "shared body error remains visible in output tabs");
  for (const step of ["checks", "commit"]) {
    await openDrawer(task.id, route(1, "result", step)); await tick();
    assert(!changes(), "non-agent panels retain their existing output");
  }
  closeDrawer();
}

async function promptChangeRaces() {
  const task = { id: "prompt-races", title: "Prompt races", column: "held", attempt: 2 };
  const list = [attempt("implement", 1), attempt("implement", 2, { after: "repeat", repeat_of: 1 })];
  const pending = [];
  const routes = [];
  initDrawer({
    detail: async () => ({ task, attempts: list.map((a) => ({ ...a })) }), tracker: async () => ({}),
    body: (_id, _step, n) => new Promise((resolve) => { pending.push({ n, resolve }); }),
  }, new Map([[task.id, task]]), (selection) => routes.push(selection));
  await openDrawer(task.id, route(1));
  await openDrawer(task.id, route(2));
  await onTaskMoved({ ...task, status: "refreshed" });
  const count = routes.length;
  pending[1].resolve(comparison("Newest", [[0, 1]])); await tick();
  assert(changes().textContent.includes("Newest") && !changes().textContent.includes("Loading"),
    "pending body redraws the same selection after detail objects are refreshed");
  pending[0].resolve(comparison("Other attempt", [[0, 1]])); await tick();
  assert(changes().textContent.includes("Newest") && !pane().textContent.includes("Other attempt"),
    "late reply cannot display another attempt's changes");
  assert(routes.length === count && pending.length === 2, "body replies do not navigate or duplicate requests");
  await openDrawer(task.id, route(1)); await tick();
  assert(changes().textContent.includes("Other attempt") && pending.length === 2, "late reply is cached only for its owning attempt");
  closeDrawer();
  await openDrawer(task.id, route(2));
  closeDrawer();
  await openDrawer(task.id, route(2));
  pending[2].resolve(comparison("Closed drawer reply", [[0, 1]])); await tick();
  assert(changes().textContent.includes("Loading changes") && !pane().textContent.includes("Closed drawer reply"),
    "reply from a closed drawer cannot enter a reopened drawer with the same selection");
  pending[3].resolve(comparison("Reopened", [[0, 1]])); await tick();
  assert(changes().textContent.includes("Reopened") && changes().textContent.includes("1 prompt line added"),
    "reopened drawer owns its new request and singular addition count");
  list[1].state = "succeeded";
  await onTaskMoved({ ...task, status: "finished" });
  assert(pending.length === 5 && changes().textContent.includes("Loading changes"), "state change invalidates the shared body cache");
  pending[4].resolve(comparison("Finished", [[0, 1]], "a".repeat(40), null)); await tick();
  assert(changes().textContent.includes("Finished") && changes().textContent.includes(`${"a".repeat(40)} → unavailable`),
    "refreshed comparison retains an unavailable new base");
  closeDrawer();
}
