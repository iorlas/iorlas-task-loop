// The task drawer: a rail of the task's steps on the left, one selected attempt on the right (its lines, its result and the prompt
// it was given), and the task as the tracker holds it. It opens from factory.db and the evidence files at once; the tracker's
// fields (`bd` calls) load second and fill the Task view in. Shapes: docs/design/dashboard-ui.md.

import { $, COLUMNS, JUMP, LAND, STATE, VERIFY, ago, callout, el, position, quietSpan, stepInfo, tag } from "./ui.js";
import { apply, atBottom, lines, setNote, show, touchQuiet } from "./lines.js";
import { causeLink, lasted, rail, verifyTitle } from "./rail.js";
import { prompt, result } from "./result.js";
import { taskView } from "./taskview.js";

let source = null;
let tasks = null;
let open = null; // {id, detail, tracker, abort, sig, bodies, opened, step, n, tab, view}: the open task, its selected attempt and sub-tabs

export function initDrawer(src, taskMap) {
  source = src;
  tasks = taskMap;
  $("backdrop").addEventListener("click", closeDrawer);
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
}

const attemptOf = () => open.detail?.attempts.find((a) => a.step === open.step && a.n === open.n);
const tabOf = (a) => (a.step === VERIFY.id ? "result" : open.tab ?? (a.state === "running" ? "lines" : "result")); // a verification has only its result
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
  const mine = { id, detail: null, tracker: { state: "loading" }, abort: new AbortController(), sig: null, bodies: new Map(), opened: new Map(), tab: null, view: null };
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

// One tracker read at a time per drawer: a retry cancels the read still in flight, and only the latest read may fill the view in.
async function loadTracker(mine) {
  mine.load?.abort();
  const own = new AbortController();
  mine.load = own;
  mine.tracker = { state: "loading" };
  mine.abort.signal.addEventListener("abort", () => own.abort(), { once: true });
  let found;
  try {
    found = { state: "ready", ...(await source.tracker(mine.id, own.signal)) };
  } catch (error) {
    if (own.signal.aborted) return;
    found = error.status === 404 ? { state: "none" } : { state: "failed", error: error.message ?? String(error) };
  }
  if (mine.load !== own) return;
  mine.tracker = found;
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
    if (!a || a.state !== "running" || a.step === "checks" || a.step === VERIFY.id) return; // checks and verifications have no agent lines
    try {
      const page = await source.feed(mine.id, a.step, a.n, a.feed_cursor ?? "0:0"); // a file not there yet follows from its start
      if (open !== mine || attemptOf() !== a) return;
      a.feedError = null;
      setNote(a);
      a.feed_cursor = page.cursor ?? a.feed_cursor;
      if (page.replaced) a.feed = a.feed.filter((e) => e.type === "step");
      for (const e of page.events) apply(a, e);
      if (page.replaced) render();
      else page.events.forEach((e) => show(a, e));
      touchQuiet(a);
    } catch (error) {
      if (open !== mine || attemptOf() !== a) return;
      a.feedError = error.message ?? String(error); // shown, and the next poll continues from the same cursor
      setNote(a);
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

// What the card says about the task's place: the column, and for a land the real state (waiting for the person, or landing).
function placeOf(t) {
  const col = COLUMNS.find((c) => c.id === t.column);
  if (t.column !== "land") return { label: `${col.emoji} ${col.label}`, help: col.help };
  const word = LAND[t.land ?? "waiting"];
  return { label: `${col.emoji} ${col.label} · ${word.label}`, help: t.land === "landing" ? "A land is putting the checked change on main now." : t.land === "manual" ? "Checked and ready; the profile says land: manual, so it waits for a person." : "Checked and ready; the next round lands it." };
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
  const railTop = $("rail")?.scrollTop ?? 0;
  const kept = $("tail") && { key: $("tail").dataset.key, top: $("tail").scrollTop, bottom: atBottom($("tail")) };
  drawer.replaceChildren();
  if (!t) return drawer.append(el("p", "px-6 py-5 text-sm text-slate-500", `Loading ${open.id}…`));
  drawer.append(head(t));
  if (t.hold_cause) {
    const hold = el("div", "px-6 pb-3");
    hold.append(callout("border-rose-500", "Held", t.hold_cause));
    drawer.append(hold);
  }
  if (t.column === "land" && t.land === "manual") {
    const waiting = el("div", "px-6 pb-3");
    waiting.append(callout(LAND.manual.bar, "Waiting for a person to land it", "The profile (.task-loop.json on main) says land: manual. Set it to auto and rounds land checked tasks by themselves."));
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
  if ($("rail") && railTop) $("rail").scrollTop = railTop;
  else body.querySelector("[data-selected]")?.scrollIntoView({ block: "nearest" });
  const tail = $("tail");
  if (tail) tail.scrollTop = kept && kept.key === tail.dataset.key && !kept.bottom ? kept.top : tail.scrollHeight;
}

// ---------- selected attempt ----------

// The Result and Prompt tabs read files, so they load when first shown (and again when the attempt has ended since).
function bodyTab(a, tab) {
  const key = `${a.step}/${a.n}`;
  const mine = open;
  const kept = mine.bodies.get(key);
  if (kept?.body) return tab === "result" ? result(a, kept.body, { key, opened: mine.opened }) : prompt(a, kept.body);
  if (kept?.error) return el("p", "px-6 py-4 text-sm text-rose-700 dark:text-rose-300", `This attempt cannot be read: ${kept.error}`);
  if (!kept) {
    mine.bodies.set(key, { state: a.state });
    source.body(mine.id, a.step, a.n).then(
      (body) => mine.bodies.set(key, { state: a.state, body }),
      (error) => mine.bodies.set(key, { state: a.state, error: error.message ?? String(error) }),
    ).then(() => { if (open === mine && attemptOf() === a) render(); });
  }
  return el("p", "px-6 py-4 text-sm text-slate-500", "Loading…");
}

const TABS = [["lines", "Lines"], ["result", "Result"], ["prompt", "Prompt"]];
const nameOf = stepInfo;

// "Began after a repeat of Implement, try 1 · why": the reason is also the hover text, and the rail's jump line selects this attempt.
function began(a) {
  const list = open.detail.attempts;
  const prev = a.after === "repeat" ? list.find((x) => x.step === a.step && x.n === a.repeat_of) : list.slice(0, list.indexOf(a)).findLast((x) => x.step !== VERIFY.id);
  const at = `${nameOf(prev?.step ?? a.step).label}${prev ? `, try ${prev.n}` : ""}`;
  const what = a.after === "repeat" ? `a repeat of ${at}` : `a restart at plan (after ${at})`;
  const line = el("p", `w-full text-xs ${JUMP[a.after].text}`);
  line.append(el("span", "font-medium", `Began after ${what}`), el("span", "text-slate-500 dark:text-slate-400", a.reason ? ` · ${a.reason}` : ""));
  line.title = a.reason ?? "";
  if (a.led_by) line.append(" ", causeLink(a, select));
  return line;
}

function pane() {
  const a = attemptOf();
  const st = STATE[a.state];
  const tab = tabOf(a);
  const wrap = el("section", "flex min-w-0 flex-1 flex-col");
  const top = el("div", "flex flex-wrap items-center gap-x-3 gap-y-1 px-6 pt-4");
  top.append(el("h3", "text-sm font-semibold", a.step === VERIFY.id ? `${VERIFY.emoji} ${verifyTitle(open.detail.attempts, a)}` : `${nameOf(a.step).emoji} ${nameOf(a.step).label}, try ${a.n}`), tag(st.label, { dotCls: st.dot, cls: st.text }));
  const timing = a.state === "running" ? "still running" : a.ended_at && a.started_at ? `ran ${lasted(a)}` : "end not recorded";
  if (a.step !== VERIFY.id) top.append(el("span", "text-xs text-slate-500 dark:text-slate-400", `${a.started_at ? `started ${ago(a.started_at)}, ` : ""}${timing}`));
  if (a.state === "running" && (a.feed.at(-1)?.at ?? a.started_at)) {
    const quiet = quietSpan(a.feed.at(-1)?.at ?? a.started_at);
    quiet.id = "quiet";
    top.append(quiet);
  }
  wrap.append(top);
  if (a.after) top.append(began(a)); // one compact line; the rail's jump line, selectable, holds the full story
  const bar = el("div", "mt-3 flex gap-5 border-b border-slate-200 px-6 dark:border-slate-800");
  for (const [id, label] of TABS) {
    const on = id === tab;
    const b = el("button", `-mb-px border-b-2 pb-2 text-[13px] ${on ? "border-slate-900 font-semibold dark:border-slate-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, label);
    b.type = "button";
    b.addEventListener("click", () => { open.tab = id; render(); });
    bar.append(b);
  }
  wrap.append(...(a.step === VERIFY.id ? [] : [bar]), tab === "lines" ? lines(a) : bodyTab(a, tab));
  return wrap;
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
    for (const a of fresh.attempts) if (open.bodies.get(`${a.step}/${a.n}`)?.state !== a.state) open.bodies.delete(`${a.step}/${a.n}`);
    open.detail = fresh;
  } catch (error) {
    return showError(open.id, error);
  }
  open.sig = signature(task);
  if (following || !attemptOf()) select();
  else render();
  follow();
}
