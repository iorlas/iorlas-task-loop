// Task loop dashboard page: the board. Plain ES modules, no framework, no build step.
// It consumes the shapes in docs/design/dashboard-ui.md from the JSON endpoints and the event stream (api.js).

import { initDrawer, onTaskMoved, openDrawer } from "./drawer.js";
import { initLogs, loadLogs, onLog } from "./logs.js";
import { apiSource } from "./api.js";
import { receiveDuration } from "./duration.js";
import {
  $, COLUMNS, LAND, STEPS, callout, el, holdCallout, isWaiting, position, quietSpan, runningAgent, tag, tick, waitingNote,
} from "./ui.js";

const tasks = new Map(); // id -> board card
const cards = new Map(); // id -> element
const columnHeads = new Map(); // column id -> count element
const cells = new Map(); // "lane|column" -> element
let slotNames = [];
let notice = null; // why the board may be stale (the tracker could not be read)
let lanes = false;
let source = null;
const streamLabel = tag("Stream connecting");
const roundLabel = tag("Last round unavailable");
let backlog = null;
let roundAt = null;
let logReload = 0;
let roundRevision = 0;
let roundsState = null;
let roundsRevision = 0;

// Only the owning reader's rows for this dashboard's backlog can advance these observations.
function roundTime(row, label, move = "round") {
  if (row.backlog !== label || row.move !== move || !Number.isFinite(Date.parse(row.at))) return null;
  return new Date(row.at).toISOString().replace(".000Z", "Z") === row.at ? row.at : null;
}

function recordedRounds(row, label) {
  const at = roundTime(row, label, "rounds");
  const word = row.words?.[0];
  return at !== null && ["started", "wait", "stopped"].includes(word) ? { at, word } : null;
}

function renderRound() {
  delete roundLabel.dataset.since;
  roundLabel.title = roundAt ?? "";
  if (roundAt === null) {
    roundLabel.textContent = "No round in available log";
  } else if (Date.parse(roundAt) > Date.now()) {
    roundLabel.textContent = "Last recorded round is in the future (clock discrepancy)";
  } else {
    roundLabel.dataset.since = roundAt;
    roundLabel.dataset.prefix = "Last recorded round ";
    roundLabel.dataset.suffix = " ago";
    tick(roundLabel);
  }
}

async function reloadRound() {
  const reload = ++logReload;
  const revision = roundRevision;
  const stateRevision = roundsRevision;
  try {
    const log = await source.logs();
    if (reload !== logReload) return;
    const streamed = backlog === log.backlog && roundsRevision !== stateRevision ? roundsState : null;
    backlog = log.backlog;
    roundsState = null;
    for (const row of log.rows) {
      const state = recordedRounds(row, backlog);
      if (state && (roundsState === null || state.at >= roundsState.at)) roundsState = state;
    }
    if (streamed && (roundsState === null || streamed.at >= roundsState.at)) roundsState = streamed;
    const times = log.rows.map((row) => roundTime(row, backlog)).filter((at) => at !== null);
    if (roundRevision !== revision && roundAt !== null) times.push(roundAt);
    roundAt = times.sort().at(-1) ?? null;
    renderRound();
    renderBoard();
  } catch {
    if (reload !== logReload) return;
    if (stateRevision === roundsRevision) {
      roundsState = null;
      renderBoard();
    }
    if (revision !== roundRevision) return;
    roundAt = null;
    delete roundLabel.dataset.since;
    roundLabel.title = "";
    roundLabel.textContent = "Last round unavailable";
  }
}

function observeRound(row) {
  const at = roundTime(row, backlog);
  if (at !== null) {
    roundRevision++;
    if (roundAt === null || at > roundAt) roundAt = at;
    renderRound();
  }
  const state = recordedRounds(row, backlog);
  if (state === null) return;
  roundsRevision++;
  if (roundsState === null || state.at >= roundsState.at) {
    roundsState = state;
    renderBoard();
  }
}

const rects = () => new Map([...cards].map(([id, node]) => [id, node.getBoundingClientRect()]));
const laneIds = () => (lanes ? [...slotNames, "none"] : ["all"]);
const laneOf = (t) => (lanes ? t.slot || "none" : "all");
const isAsk = (t) => t.column === "held" && Boolean(t.ask);

function buildBoard() {
  const board = $("board");
  board.replaceChildren();
  columnHeads.clear();
  cells.clear();
  board.style.gridTemplateColumns = `${lanes ? "5.5rem " : ""}repeat(7, minmax(0, 1fr))`;
  board.style.gridTemplateRows = lanes ? `auto repeat(${slotNames.length + 1}, max-content)` : "auto minmax(0, 1fr)";
  board.style.alignContent = lanes ? "start" : "";
  board.classList.toggle("overflow-y-auto", lanes);
  const sticky = "sticky top-0 z-20 bg-slate-100 dark:bg-slate-950";
  if (lanes) board.append(el("div", sticky));
  for (const col of COLUMNS) {
    const head = el("div", `${sticky} flex items-center gap-2 px-1 pb-2`);
    head.title = col.help;
    const count = el("span", "ml-auto text-xs tabular-nums text-slate-400 dark:text-slate-500", "0");
    head.append(el("span", "text-sm", col.emoji), el("h2", "text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-300", col.label), count);
    board.append(head);
    columnHeads.set(col.id, count);
  }
  for (const lane of laneIds()) {
    if (lanes) board.append(el("div", "pt-2.5 font-mono text-[11px] text-slate-500 dark:text-slate-400", lane === "none" ? "no slot" : lane));
    for (const col of COLUMNS) {
      const cell = el("div", `flex min-w-0 flex-col gap-2 rounded-lg bg-slate-200/40 p-1.5 dark:bg-slate-900/50 ${lanes ? "min-h-14" : "min-h-0 overflow-y-auto"}`);
      board.append(cell);
      cells.set(`${lane}|${col.id}`, cell);
    }
  }
}

const TIME = {
  plan: ["", " in step"], implement: ["", " in step"], checks: ["", " in step"], land: ["", " in step"],
  held: ["on hold ", ""], landed: ["landed ", " ago"],
};

function fillCard(node, t) {
  node.replaceChildren();
  delete node.dataset.quietLevel;
  const top = el("div", "flex items-center gap-2");
  top.append(el("span", "font-mono text-[11px] text-slate-500 dark:text-slate-400", t.id));
  if (position(t)) top.append(el("span", "ml-auto text-[11px] text-slate-500 dark:text-slate-400", position(t)));
  node.append(top, el("h3", "mt-1 line-clamp-2 text-[13px] font-medium leading-snug", t.title));
  const notes = el("div", "mt-2 flex flex-col gap-2");
  if (t.repeat) {
    const restart = t.repeat.kind === "restart_at_plan";
    notes.append(callout(restart ? "border-violet-500" : "border-amber-500", restart ? "↩ Restarted at plan" : "↻ Repeat", t.repeat.reason));
  }
  const hold = holdCallout(t);
  if (hold) notes.append(hold);
  if (t.column === "waiting" || t.column === "land") {
    const word = LAND[t.land ?? "unknown"];
    const note = callout(t.column === "land" ? word.bar : "border-slate-400",
      t.column === "land" ? word.label : t.status === "abandoned" ? "Abandoned" : "Queued");
    if (isWaiting(t)) note.append(waitingNote(t));
    else if (t.status_note) note.append(el("p", "text-xs", t.status_note));
    if (t.column === "land" && t.land === "waiting" && roundsState?.word === "stopped") {
      note.append(el("p", "text-xs", "Rounds last recorded as stopped; automatic landing awaits rounds resuming."));
    }
    notes.append(note);
  }
  if (notes.children.length) node.append(notes);
  const foot = el("div", "mt-2.5 flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400");
  const time = el("span", "whitespace-nowrap tabular-nums");
  if (!isWaiting(t) && (t.step_started_at || (runningAgent(t) && t.duration && !t.duration.frozen))) {
    [time.dataset.prefix, time.dataset.suffix] = TIME[t.column];
    if (runningAgent(t) && t.duration && !t.duration.frozen) time.dataset.duration = t.duration.execution;
    else time.dataset.since = t.step_started_at;
    foot.append(time);
    tick(time);
  }
  if (t.slot && !lanes) foot.append(el("span", "ml-auto font-mono", t.slot));
  node.append(foot);
  if (runningAgent(t) && t.duration && !t.duration.frozen) {
    const quiet = quietSpan(t.duration);
    node.append(quiet);
    tick(quiet);
  }
}

function newCard(t) {
  const node = el("article", "relative cursor-pointer rounded-md border border-slate-200 bg-white p-3 transition-colors hover:border-slate-400 data-[quiet-level=slow]:border-amber-400 data-[quiet-level=long]:border-rose-400 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600");
  node.dataset.id = t.id;
  node.addEventListener("click", () => openDrawer(t.id));
  return node;
}

function renderBoard(first = rects()) {
  const all = [...tasks.values()];
  for (const col of COLUMNS) columnHeads.get(col.id).textContent = String(all.filter((t) => t.column === col.id).length);
  for (const lane of laneIds()) {
    for (const col of COLUMNS) {
      const cell = cells.get(`${lane}|${col.id}`);
      all.filter((t) => t.column === col.id && laneOf(t) === lane)
        .sort((a, b) => Number(isAsk(b)) - Number(isAsk(a)) || Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at))
        .forEach((t, i) => {
          if (!cards.has(t.id)) cards.set(t.id, newCard(t));
          const node = cards.get(t.id);
          fillCard(node, t);
          if (cell.children[i] !== node) cell.insertBefore(node, cell.children[i] || null);
        });
    }
  }
  for (const [id, node] of cards) {
    const before = first.get(id);
    if (!before) continue;
    const after = node.getBoundingClientRect();
    const dx = before.left - after.left;
    const dy = before.top - after.top;
    if (!dx && !dy) continue;
    node.style.zIndex = "10";
    node.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: 650, easing: "cubic-bezier(.2,.8,.2,1)" })
      .finished.then(() => { node.style.zIndex = ""; }, () => {});
    if (dx) {
      node.classList.remove("animate-flash");
      void node.offsetWidth;
      node.classList.add("animate-flash");
    }
  }
  const running = all.filter((t) => STEPS.some((s) => s.id === t.column)).length;
  const held = all.filter((t) => t.column === "held").length;
  const attention = `${all.filter(isAsk).length} need you`;
  $("summary").textContent = `${all.length} tasks · ${running} running · ${attention} · ${held} on hold`
    + (notice ? ` · ${notice}` : "");
}

const viewButton = (on) => `rounded px-2.5 py-1 text-xs font-medium ${on ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`;

function setLanes(on) {
  const first = rects();
  lanes = on;
  $("view-columns").className = viewButton(!on);
  $("view-lanes").className = viewButton(on);
  buildBoard();
  renderBoard(first);
}

const navButton = (on) => `rounded px-2.5 py-1 text-sm font-medium ${on ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`;

function showScreen(name) {
  $("board").hidden = name !== "board";
  $("logs").hidden = name !== "logs";
  $("layout").hidden = name !== "board";
  $("nav-board").className = navButton(name === "board");
  $("nav-logs").className = navButton(name === "logs");
  if (name === "logs") loadLogs(source);
}

// The board cannot be read (factory.db gone or of another version, the server failing): say so and show no cards at all, never
// the last ones. The stream's `resync` brings the board back when it can be read again.
function fail(error) {
  $("banner").textContent = `The factory cannot be read: ${error.message ?? error}`;
  $("banner").hidden = false;
  for (const node of cards.values()) node.remove();
  cards.clear();
  tasks.clear();
  notice = null;
  renderBoard();
}

function drop(id) {
  cards.get(id)?.remove();
  cards.delete(id);
  tasks.delete(id);
}

// After a reconnect or an error the stream may have missed moves: load the board again and drop cards that are gone.
async function resyncBoard() {
  let snap;
  try {
    snap = await source.snapshot();
  } catch (error) {
    return fail(error);
  }
  $("banner").hidden = true;
  const ids = new Set(snap.tasks.map((t) => t.id));
  for (const id of [...cards.keys()]) if (!ids.has(id)) drop(id);
  slotNames = snap.slots;
  for (const t of snap.tasks) {
    receiveDuration(t.duration);
    tasks.set(t.id, t);
    onTaskMoved(t);
  }
  notice = snap.notice;
  if (lanes) buildBoard();
  renderBoard();
}

async function resync() {
  await Promise.all([resyncBoard(), reloadRound()]);
}

function toggleTheme() {
  const root = document.documentElement;
  const dark = root.classList.contains("dark") || (!root.classList.contains("light") && matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", !dark);
  root.classList.toggle("light", dark);
  try { localStorage.setItem("dash-theme", dark ? "light" : "dark"); } catch { /* storage may be blocked */ }
}

async function start() {
  try {
    const saved = localStorage.getItem("dash-theme");
    if (saved) document.documentElement.classList.add(saved);
  } catch { /* storage may be blocked */ }
  $("theme").addEventListener("click", toggleTheme);
  $("nav-board").addEventListener("click", () => showScreen("board"));
  $("nav-logs").addEventListener("click", () => showScreen("logs"));
  $("view-columns").addEventListener("click", () => setLanes(false));
  $("view-lanes").addEventListener("click", () => setLanes(true));
  source = apiSource();
  $("mode").className = "inline-flex items-center gap-2";
  $("mode").replaceChildren(streamLabel, roundLabel);
  initDrawer(source, tasks);
  initLogs(openDrawer);
  setLanes(false);
  showScreen("board");
  await resync();
  source.subscribe(async (msg) => {
    if (msg.kind === "resync") return resync();
    if (msg.kind === "error") return fail(new Error(msg.error));
    if (msg.kind === "gone") {
      drop(msg.id);
      return renderBoard();
    }
    if (msg.kind === "log") {
      observeRound(msg.row);
      return onLog(msg.row);
    }
    receiveDuration(msg.task.duration);
    tasks.set(msg.task.id, msg.task);
    renderBoard();
    onTaskMoved(msg.task);
  }, (connected) => { streamLabel.textContent = connected ? "Stream connected" : "Stream disconnected"; });
  setInterval(() => {
    document.querySelectorAll("[data-since],[data-duration],[data-quiet],[data-waiting-since]").forEach(tick);
    // A future observation may become an elapsed time once the local clock catches up.
    if (roundAt !== null) renderRound();
  }, 1000);
}

start();
