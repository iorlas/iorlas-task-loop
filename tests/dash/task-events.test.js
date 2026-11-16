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
}
