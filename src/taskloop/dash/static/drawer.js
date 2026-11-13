// The task drawer: a rail of the task's steps on the left, one selected attempt on the right (its lines, its result and the prompt
// it was given), and the task as the tracker holds it. It opens from factory.db and the evidence files at once; the tracker's
// fields (`bd` calls) load second and fill the Task view in. Shapes: docs/design/dashboard-ui.md.

import { $, COLUMNS, JUMP, LAND, STATE, STEPS, ago, callout, el, fmtDur, position, quietSpan, tag } from "./ui.js";
import { apply, atBottom, lines, show } from "./lines.js";
import { lasted, rail } from "./rail.js";
import { taskView } from "./taskview.js";

let source = null;
let tasks = null;
let open = null; // {id, detail, tracker, abort, sig, step, n, tab, view}: the open task, its selected attempt and sub-tabs

export function initDrawer(src, taskMap) {
  source = src;
  tasks = taskMap;
  $("backdrop").addEventListener("click", closeDrawer);
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
}

const attemptOf = () => open.detail?.attempts.find((a) => a.step === open.step && a.n === open.n);
const tabOf = (a) => open.tab ?? (a.state === "running" ? "lines" : "result");
const signature = (t) => JSON.stringify([t.column, t.attempt, t.repeat, t.slot, t.hold_cause, t.land]); // what changes the attempts

// Select an attempt: the given one, else the last of the step, else the last of the task.
function select(step, n) {
  const list = open.detail.attempts;
  const a = n != null ? list.find((x) => x.step === step && x.n === n) : list.findLast((x) => !step || x.step === step) ?? list.at(-1);
  open.step = a?.step;
  open.n = a?.n;
  render();
}

function reveal() {
  $("drawer").classList.remove("translate-x-full");
  $("backdrop").classList.remove("pointer-events-none", "opacity-0");
}

// Open at once: the board's card is the head and the body says loading; the detail (factory.db and files, milliseconds) renders when
// it arrives and the tracker's fields (`bd`, slow under load) when they do. Opening another task cancels the first one's tracker read.
export async function openDrawer(id) {
  open?.abort.abort();
  const mine = { id, detail: null, tracker: { state: "loading" }, abort: new AbortController(), sig: null, tab: null, view: null };
  open = mine;
  render();
  reveal();
  loadTracker(mine);
  try {
    mine.detail = await source.detail(id);
  } catch (error) {
    if (open === mine) showError(id, error);
    return;
  }
  if (open !== mine) return;
  mine.sig = signature(tasks.get(id) || mine.detail.task);
  select();
  follow();
}

async function loadTracker(mine) {
  mine.tracker = { state: "loading" };
  try {
    mine.tracker = { state: "ready", ...(await source.tracker(mine.id, mine.abort.signal)) };
  } catch (error) {
    if (mine.abort.signal.aborted) return;
    mine.tracker = error.status === 404 ? { state: "none" } : { state: "failed", error: error.message ?? String(error) };
  }
  if (open === mine && taskTabOpen()) render();
}

const taskTabOpen = () => (open.view ?? (open.detail?.attempts.length ? "attempts" : "task")) === "task";

const FOLLOW_MS = 2000;
let follower = null;

// While the drawer shows a running attempt, ask for the lines after the cursor of the last answer. Closing the drawer or selecting
// another attempt stops following this one; the page never jumps to the newest attempt by itself.
function follow() {
  clearInterval(follower);
  follower = setInterval(async () => {
    const mine = open;
    const a = mine && attemptOf();
    if (!a || a.state !== "running" || !a.feed_cursor) return;
    try {
      const page = await source.feed(mine.id, a.step, a.n, a.feed_cursor);
      if (open !== mine || attemptOf() !== a) return;
      a.feed_cursor = page.cursor ?? a.feed_cursor;
      if (page.replaced) a.feed = a.feed.filter((e) => e.type === "step");
      for (const e of page.events) apply(a, e);
      if (page.replaced) render();
      else page.events.forEach((e) => show(a, e));
    } catch {
      // a missed poll is not an error: the next one continues from the same cursor
    }
  }, FOLLOW_MS);
}

// The task could not be read: say so in the drawer, with nothing from an earlier read.
function showError(id, error) {
  const head = el("header", "flex items-start gap-4 px-6 py-5");
  const close = el("button", "rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 dark:border-slate-700", "Close");
  close.type = "button";
  close.addEventListener("click", closeDrawer);
  const who = el("div", "min-w-0 flex-1");
  who.append(el("p", "font-mono text-xs text-slate-500", id));
  head.append(who, close);
  $("drawer").replaceChildren(head, el("p", "px-6 text-sm text-rose-700 dark:text-rose-300", `This task cannot be read: ${error.message ?? error}`));
}

export function closeDrawer() {
  clearInterval(follower);
  open?.abort.abort();
  open = null;
  $("drawer").classList.add("translate-x-full");
  $("backdrop").classList.add("pointer-events-none", "opacity-0");
}

const VIEWS = [["attempts", "Steps"], ["task", "Task"]];

// What the card says about the task's place: the column, and for a land the real state (waiting for the person, or delivering).
function placeOf(t) {
  const col = COLUMNS.find((c) => c.id === t.column);
  if (t.column !== "land") return { label: `${col.emoji} ${col.label}`, help: col.help };
  const word = LAND[t.land ?? "waiting"];
  return { label: `${col.emoji} ${col.label} · ${word.label}`, help: t.land === "delivering" ? "A land is delivering the checked change to main." : "Checked and ready; the factory never lands by itself." };
}

function head(t) {
  const place = placeOf(t);
  const wrap = el("header", "flex items-start gap-4 px-6 pb-3 pt-5");
  const title = el("div", "min-w-0 flex-1");
  const status = el("div", "flex items-center gap-2");
  status.append(el("span", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id), tag(place.label, { cls: "text-slate-700 dark:text-slate-200" }));
  if (t.slot) status.append(tag(`slot ${t.slot}`, { cls: "font-mono" }));
  if (position(t)) status.append(el("span", "text-xs text-slate-500 dark:text-slate-400", position(t)));
  status.append(el("span", "truncate text-xs text-slate-500 dark:text-slate-400", place.help));
  title.append(status, el("h2", "mt-1.5 text-lg font-semibold leading-snug", t.title));
  const close = el("button", "rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800", "Close");
  close.type = "button";
  close.addEventListener("click", closeDrawer);
  wrap.append(title, close);
  return wrap;
}

// Rebuild the drawer. The Lines tab keeps its scroll place across a rebuild of the same attempt: at the bottom it stays at the bottom,
// anywhere else it stays where it was; a different attempt or tab starts at the bottom.
function render() {
  if (!open) return;
  const { detail } = open;
  const t = tasks.get(open.id) || detail?.task;
  const drawer = $("drawer");
  const kept = $("tail") && { key: $("tail").dataset.key, top: $("tail").scrollTop, bottom: atBottom($("tail")) };
  drawer.replaceChildren();
  if (!t) return drawer.append(el("p", "px-6 py-5 text-sm text-slate-500", `Loading ${open.id}…`));
  drawer.append(head(t));
  if (t.hold_cause) {
    const hold = el("div", "px-6 pb-3");
    hold.append(callout("border-rose-500", "Held", t.hold_cause));
    drawer.append(hold);
  }
  if (t.column === "land" && t.land !== "delivering") {
    const waiting = el("div", "px-6 pb-3");
    waiting.append(callout(LAND.waiting.bar, "Waiting for you to land it", `Run: tl step land ${t.id}`));
    drawer.append(waiting);
  }
  if (!detail) return drawer.append(el("p", "px-6 py-5 text-sm text-slate-500", "Loading the task's steps…"));

  const view = open.view ?? (detail.attempts.length ? "attempts" : "task");
  const bar = el("div", "flex gap-5 border-b border-slate-200 px-6 dark:border-slate-800");
  for (const [id, label] of VIEWS) {
    const on = id === view;
    const b = el("button", `-mb-px border-b-2 pb-2 text-sm ${on ? "border-slate-900 font-semibold dark:border-slate-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, id === "attempts" && detail.attempts.length ? `${label} ${detail.attempts.length}` : label);
    b.type = "button";
    b.addEventListener("click", () => { open.view = id; render(); });
    bar.append(b);
  }
  drawer.append(bar);

  if (view === "task") return drawer.append(taskView(open.tracker, () => { loadTracker(open); render(); }));
  if (!detail.attempts.length) return drawer.append(el("p", "px-6 py-5 text-sm text-slate-500", "Not started: no attempt yet."));
  const body = el("div", "flex min-h-0 flex-1");
  body.append(rail(detail.attempts, t, open, select), pane());
  drawer.append(body);
  body.querySelector("[data-selected]")?.scrollIntoView({ block: "nearest" });
  const tail = $("tail");
  if (tail) tail.scrollTop = kept && kept.key === tail.dataset.key && !kept.bottom ? kept.top : tail.scrollHeight;
}

// ---------- selected attempt ----------

const TABS = [["lines", "Lines"], ["result", "Result"], ["prompt", "Prompt"]];
const nameOf = (id) => STEPS.find((s) => s.id === id);

function pane() {
  const a = attemptOf();
  const st = STATE[a.state];
  const tab = tabOf(a);
  const wrap = el("section", "flex min-w-0 flex-1 flex-col");
  const top = el("div", "flex flex-wrap items-center gap-x-3 gap-y-1 px-6 pt-4");
  top.append(el("h3", "text-sm font-semibold", `${nameOf(a.step).emoji} ${nameOf(a.step).label}, try ${a.n}`), tag(st.label, { dotCls: st.dot, cls: st.text }));
  const timing = a.state === "running" ? "still running" : a.ended_at && a.started_at ? `ran ${lasted(a)}` : "end not recorded";
  top.append(el("span", "text-xs text-slate-500 dark:text-slate-400", `${a.started_at ? `started ${ago(a.started_at)}, ` : ""}${timing}`));
  if (a.state === "running" && (a.feed.at(-1)?.at ?? a.started_at)) top.append(quietSpan(a.feed.at(-1)?.at ?? a.started_at));
  wrap.append(top);
  if (a.after) {
    const why = el("div", "px-6 pt-3");
    const prev = open.detail.attempts[open.detail.attempts.indexOf(a) - 1];
    const what = a.after === "repeat" ? "Repeat of" : "Back to plan after";
    why.append(callout(JUMP[a.after].bar, `${what} ${nameOf(prev.step).label}, try ${prev.n}`, a.reason));
    wrap.append(why);
  }
  const bar = el("div", "mt-3 flex gap-5 border-b border-slate-200 px-6 dark:border-slate-800");
  for (const [id, label] of TABS) {
    const on = id === tab;
    const b = el("button", `-mb-px border-b-2 pb-2 text-[13px] ${on ? "border-slate-900 font-semibold dark:border-slate-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, label);
    b.type = "button";
    b.addEventListener("click", () => { open.tab = id; render(); });
    bar.append(b);
  }
  wrap.append(bar, tab === "lines" ? lines(a) : tab === "result" ? result(a) : prompt(a));
  return wrap;
}

const BLOCK = "min-h-0 flex-1 overflow-y-auto px-6 py-4";
const pre = (text, cls = "") => el("pre", `max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-3 font-mono text-[11.5px] leading-relaxed dark:border-slate-800 dark:bg-slate-950/60 ${cls}`, text);
const label = (text) => el("h4", "mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500", text);

function result(a) {
  const box = el("div", `${BLOCK} flex flex-col gap-5`);
  const st = STATE[a.state];
  const summary = el("div");
  summary.append(label("Conclusion"), callout(a.state === "failed" ? "border-rose-500" : a.state === "running" ? "border-sky-500" : "border-emerald-500", null, a.result.summary));
  box.append(summary);
  if (a.result.answer) {
    const ans = el("div");
    ans.append(label("Agent answer"), el("p", "mb-1 text-xs"), pre(a.result.answer.text));
    ans.children[1].append(tag(a.result.answer.disposition));
    box.append(ans);
  }
  if (a.result.checks.length) {
    const wrap = el("div");
    wrap.append(label(`Checks · ${a.result.checks.length}`));
    for (const c of a.result.checks) {
      const row = el("div", "border-t border-slate-100 py-2 first:border-t-0 dark:border-slate-800/70");
      const top = el("div", "flex items-baseline gap-3 text-xs");
      top.append(el("span", "font-mono text-[12px]", c.name), el("span", `font-medium ${c.passed ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`, c.passed ? "passed" : "failed"), el("span", "ml-auto tabular-nums text-slate-500", fmtDur(c.duration_ms)));
      row.append(top);
      if (c.output) row.append(pre(c.output, "mt-2 border-l-2 border-l-rose-500"));
      wrap.append(row);
    }
    box.append(wrap);
  } else if (a.result.output) {
    const out = el("div");
    out.append(label("Output"), pre(a.result.output, "border-l-2 border-l-rose-500"));
    box.append(out);
  }
  if (a.state === "running") box.append(el("p", "text-xs text-slate-500", `${st.label}: the result is written when the attempt ends.`));
  return box;
}

function prompt(a) {
  const box = el("div", BLOCK);
  if (!a.input) {
    box.append(el("p", "text-sm text-slate-500", "No prompt: this step runs commands, not the agent."));
    return box;
  }
  box.append(label(`Input sent to the agent · ${a.input.length} characters`), pre(a.input, "max-h-none"));
  return box;
}

// A card moved. The drawer reloads the task's steps only when they can have changed (a step or try began or ended, a hold, a land);
// a card that only shows newer activity changes nothing here, and never moves the tab, the selection or the scroll place.
export async function onTaskMoved(task) {
  if (open?.id !== task.id || !open.detail || signature(task) === open.sig) return;
  const mine = open;
  const following = attemptOf()?.state === "running" && attemptOf() === open.detail.attempts.at(-1);
  try {
    const fresh = await source.detail(open.id);
    if (open !== mine) return;
    open.detail = fresh;
  } catch (error) {
    return showError(open.id, error);
  }
  open.sig = signature(task);
  if (following || !attemptOf()) select();
  else render();
  follow();
}
