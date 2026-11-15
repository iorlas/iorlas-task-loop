// The fragment owns drawer selection. Drawer caches and disclosure stay local.
import { STEPS, VERIFY } from "./ui.js";

export const TABS = [["lines", "Lines"], ["result", "Result"], ["prompt", "Prompt"]];
export const VIEWS = [["attempts", "Steps"], ["task", "Task"]];
export const ROUTE = Object.freeze({
  closed: "closed", default: "default", attempt: "attempt", task: "task", steps: "steps", land: "land",
});
const closed = () => ({ kind: ROUTE.closed });

// Routes discriminate closed, task defaults, a selected attempt, Task view, and delivery.
// Task view retains an attempt through its final /task; delivery retains it as /land/task.
// /steps retains the empty Steps view when there is no attempt identity to encode.
export function decode(hash) {
  if (!hash || hash === "#") return closed();
  const parts = hash.slice(1).split("/");
  let id;
  try { id = decodeURIComponent(parts[0]); } catch { return closed(); }
  const [, step, number, tab] = parts;
  if (!id) return closed();
  if (parts.length === 1) return { kind: ROUTE.default, id };
  if (parts.length === 2 && step === "task") return { kind: ROUTE.task, id };
  if (parts.length === 2 && step === "steps") return { kind: ROUTE.steps, id };
  if (step === "land" && (parts.length === 2 || (parts.length === 3 && number === "task"))) {
    return { kind: ROUTE.land, id, tab: number };
  }
  const n = Number(number);
  const validStep = [...STEPS.slice(0, -1), VERIFY].some((s) => s.id === step);
  const validTab = TABS.some(([value]) => value === tab) || tab === "task";
  if (parts.length !== 4 || !validStep || !/^[1-9]\d*$/.test(number) || !Number.isSafeInteger(n) || !validTab) return closed();
  return { kind: ROUTE.attempt, id, step, n, tab };
}

export function encode(route) {
  if (route.kind === ROUTE.closed) return "";
  const root = `#${encodeURIComponent(route.id)}`;
  if (route.kind === ROUTE.attempt) return `${root}/${route.step}/${route.n}/${route.tab}`;
  if (route.kind === ROUTE.land) return `${root}/land${route.tab === "task" ? "/task" : ""}`;
  if (route.kind === ROUTE.steps) return `${root}/steps`;
  return route.kind === ROUTE.task ? `${root}/task` : root;
}

export function resolveSelection(detail, request = {}) {
  const list = detail.attempts;
  const view = request.kind === ROUTE.task || request.tab === "task" ? "task"
    : list.length || request.kind === ROUTE.steps ? "attempts" : "task";
  if (request.kind === ROUTE.land) return { step: "land", n: null, tab: null, view: request.tab === "task" ? "task" : "attempts" };
  const requested = list.find((x) => x.step === request.step && x.n === request.n);
  const a = requested ?? list.at(-1);
  const tab = a?.step === VERIFY.id ? "result"
    : requested && TABS.some(([id]) => id === request.tab) ? request.tab : a?.state === "running" ? "lines" : "result";
  return { step: a?.step, n: a?.n, tab, view };
}

export function selectionRoute(open) {
  if (!open) return closed();
  const { id, step, n, tab, view } = open;
  if (!open.detail) return open.request ?? { kind: ROUTE.default, id };
  if (step === "land") return { kind: ROUTE.land, id, tab: view === "task" ? "task" : undefined };
  if (!step) return { kind: view === "attempts" ? ROUTE.steps : ROUTE.task, id };
  return { kind: ROUTE.attempt, id, step, n, tab: view === "task" ? "task" : tab };
}

export function initNavigation(apply, browser = window) {
  let seen;
  const changed = (route, replace = false) => {
    const hash = encode(route);
    if (browser.location.hash !== hash) {
      browser.history[replace ? "replaceState" : "pushState"](null, "", `${browser.location.pathname}${browser.location.search}${hash}`);
    }
    seen = browser.location.hash;
  };
  const restore = () => {
    if (seen === browser.location.hash) return;
    seen = browser.location.hash;
    const route = decode(seen);
    apply(route);
    if (route.kind === ROUTE.closed) changed(route, true);
  };
  return {
    changed,
    start() { browser.addEventListener("hashchange", restore); browser.addEventListener("popstate", restore); restore(); },
    stop() { browser.removeEventListener("hashchange", restore); browser.removeEventListener("popstate", restore); },
  };
}
