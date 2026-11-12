// Task loop dashboard page: the board. Plain ES modules, no framework, no build step.
// It consumes the shapes in docs/design/dashboard-ui.md from the JSON endpoints and the event stream (api.js).

import { initDrawer, onFeed, onTaskMoved, openDrawer } from "./drawer.js";
import { initLogs, loadLogs, onLog } from "./logs.js";
import { apiSource } from "./api.js";
import { $, COLUMNS, STEPS, callout, el, quietSpan, tag, tick } from "./ui.js";

const tasks = new Map(); // id -> board card
const cards = new Map(); // id -> element
const columnHeads = new Map(); // column id -> count element
const cells = new Map(); // "lane|column" -> element
let slotNames = [];
let notice = null; // why the board may be stale (the tracker could not be read)
let lanes = false;
let source = null;

const rects = () => new Map([...cards].map(([id, node]) => [id, node.getBoundingClientRect()]));
const laneIds = () => (lanes ? [...slotNames, "none"] : ["all"]);
const laneOf = (t) => (lanes ? t.slot || "none" : "all");

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
  waiting: ["", " ready"], plan: ["", " in step"], implement: ["", " in step"], checks: ["", " in step"], land: ["", " in step"],
  held: ["held ", ""], landed: ["landed ", " ago"],
};

function fillCard(node, t) {
  node.replaceChildren();
  const top = el("div", "flex items-center gap-2");
  top.append(el("span", "font-mono text-[11px] text-slate-500 dark:text-slate-400", t.id));
  if (t.attempt > 0) top.append(el("span", "ml-auto text-[11px] text-slate-500 dark:text-slate-400", `attempt ${t.attempt}`));
  node.append(top, el("h3", "mt-1 line-clamp-2 text-[13px] font-medium leading-snug", t.title));
  const notes = el("div", "mt-2 flex flex-col gap-2");
  if (t.repeat) {
    const restart = t.repeat.kind === "restart_at_plan";
    notes.append(callout(restart ? "border-violet-500" : "border-amber-500", restart ? "↩ Back to plan" : "↻ Repeat", t.repeat.reason));
  }
  if (t.hold_cause) notes.append(callout("border-rose-500", "Held", t.hold_cause));
  if (notes.children.length) node.append(notes);
  const foot = el("div", "mt-2.5 flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400");
  const time = el("span", "whitespace-nowrap tabular-nums");
  [time.dataset.prefix, time.dataset.suffix] = TIME[t.column];
  time.dataset.since = t.step_started_at;
  foot.append(time);
  if (t.slot && !lanes) foot.append(el("span", "ml-auto font-mono", t.slot));
  node.append(foot);
  if (STEPS.some((s) => s.id === t.column)) {
    const quiet = quietSpan(t.last_activity_at);
    node.append(quiet);
    tick(quiet);
  }
  tick(time);
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
        .sort((a, b) => Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at))
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
  $("summary").textContent = `${all.length} tasks · ${running} running · ${all.filter((t) => t.column === "held").length} held${notice ? ` · ${notice}` : ""}`;
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

// After a reconnect the stream may have missed moves: load the board again and drop cards that are gone.
async function resync() {
  const snap = await source.snapshot();
  const ids = new Set(snap.tasks.map((t) => t.id));
  for (const [id, node] of cards) if (!ids.has(id)) { node.remove(); cards.delete(id); tasks.delete(id); }
  for (const t of snap.tasks) tasks.set(t.id, t);
  notice = snap.notice;
  renderBoard();
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
  $("mode").replaceChildren(tag(source.label, { dotCls: "bg-emerald-500", cls: "text-slate-600 dark:text-slate-300" }));
  const snap = await source.snapshot();
  slotNames = snap.slots;
  notice = snap.notice;
  for (const t of snap.tasks) tasks.set(t.id, t);
  initDrawer(source, tasks);
  initLogs(openDrawer);
  setLanes(false);
  showScreen("board");
  source.subscribe(async (msg) => {
    if (msg.kind === "resync") return resync();
    if (msg.kind === "feed") return onFeed(msg);
    if (msg.kind === "log") return onLog(msg.row);
    tasks.set(msg.task.id, msg.task);
    renderBoard();
    onTaskMoved(msg.task);
  });
  setInterval(() => document.querySelectorAll("[data-since],[data-quiet]").forEach(tick), 1000);
}

start();
