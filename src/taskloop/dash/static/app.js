// Task loop dashboard page. Plain ES module, no framework, no build step.
// It consumes the shapes in docs/design/dashboard-ui.md. Only the mock source exists so far (mock.js).

import { mockSource } from "./mock.js";

const COLUMNS = [
  { id: "waiting", label: "Ready", emoji: "⏳", bar: "bg-slate-400" },
  { id: "plan", label: "Plan", emoji: "🧭", bar: "bg-sky-500" },
  { id: "implement", label: "Implement", emoji: "🛠️", bar: "bg-indigo-500" },
  { id: "checks", label: "Checks", emoji: "🧪", bar: "bg-violet-500" },
  { id: "land", label: "Land", emoji: "🚀", bar: "bg-teal-500" },
  { id: "held", label: "Held", emoji: "⛔", bar: "bg-rose-500" },
  { id: "landed", label: "Landed", emoji: "✅", bar: "bg-emerald-500" },
];
const STEPS = COLUMNS.slice(1, 5);
const FEED_LIMIT = 20;
const STATE = {
  running: { emoji: "▶️", cls: "text-emerald-700 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-400/10" },
  succeeded: { emoji: "✅", cls: "text-slate-700 bg-slate-100 dark:text-slate-300 dark:bg-slate-800" },
  failed: { emoji: "❌", cls: "text-rose-800 bg-rose-50 dark:text-rose-300 dark:bg-rose-400/10" },
};

const tasks = new Map(); // id -> board card
const cards = new Map(); // id -> element
const columnHeads = new Map(); // column id -> count element
const cells = new Map(); // "lane|column" -> element
let slotNames = [];
let lanes = false;
let source = null;
let open = null; // {id, detail, step, n}: the open task and its selected attempt

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const rects = () => new Map([...cards].map(([id, node]) => [id, node.getBoundingClientRect()]));

// ---------- formatting ----------

function fmtDur(ms) {
  if (ms < 1000) return `${Math.max(Math.round(ms), 0)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(Math.floor(s % 60)).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
const since = (iso) => fmtDur(Date.now() - Date.parse(iso));
const ago = (iso) => `${since(iso)} ago`;
// Quiet time of running work: nothing shown under 2 minutes, then amber, then red from 15 minutes. Display only.
const QUIET_AFTER_S = 120;
const QUIET_LONG_S = 900;
function tickQuiet(node) {
  const s = (Date.now() - Date.parse(node.dataset.quiet)) / 1000;
  const level = s >= QUIET_LONG_S ? "long" : s >= QUIET_AFTER_S ? "slow" : "";
  node.hidden = !level;
  node.textContent = `💤 quiet ${fmtDur(s * 1000)}`;
  node.className = `${node.closest("article") ? "mt-2 block w-fit" : ""} rounded px-1.5 text-xs font-medium ${level === "long" ? "bg-rose-100 text-rose-700 dark:bg-rose-400/15 dark:text-rose-300" : "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300"}`;
  const card = node.closest("article");
  if (card) card.dataset.quietLevel = level;
}
const tick = (node) => {
  if (node.dataset.quiet) return tickQuiet(node);
  node.textContent = `${node.dataset.prefix || ""}${since(node.dataset.since)}${node.dataset.suffix || ""}`;
};

// ---------- board ----------

const laneIds = () => (lanes ? [...slotNames, "none"] : ["all"]);
const laneOf = (t) => (lanes ? t.slot || "none" : "all");

function buildBoard() {
  const board = $("board");
  board.replaceChildren();
  columnHeads.clear();
  cells.clear();
  board.style.gridTemplateColumns = `${lanes ? "7rem " : ""}repeat(7, minmax(0, 1fr))`;
  board.style.gridTemplateRows = lanes ? `auto repeat(${slotNames.length + 1}, max-content)` : "auto minmax(0, 1fr)";
  board.style.alignContent = lanes ? "start" : "";
  board.classList.toggle("overflow-y-auto", lanes);
  if (lanes) board.append(el("div", "sticky top-0 z-20 bg-slate-100 dark:bg-slate-950"));
  for (const col of COLUMNS) {
    const head = el("div", "sticky top-0 z-20 flex items-center gap-2 bg-slate-100 px-3 pb-1 dark:bg-slate-950");
    const count = el("span", "ml-auto rounded-full bg-white px-2 text-xs tabular-nums text-slate-500 dark:bg-slate-800 dark:text-slate-400", "0");
    head.append(el("span", `h-2 w-2 rounded-full ${col.bar}`), el("h2", "text-sm font-semibold", `${col.emoji} ${col.label}`), count);
    board.append(head);
    columnHeads.set(col.id, count);
  }
  for (const lane of laneIds()) {
    if (lanes) board.append(el("div", "pt-3 pl-1 font-mono text-xs text-slate-500 dark:text-slate-400", lane === "none" ? "no slot" : `🧩 slot ${lane}`));
    for (const col of COLUMNS) {
      const cell = el("div", `flex min-w-0 flex-col gap-2 rounded-xl bg-slate-200/50 p-2 dark:bg-slate-900/60 ${lanes ? "min-h-16" : "min-h-0 overflow-y-auto"}`);
      board.append(cell);
      cells.set(`${lane}|${col.id}`, cell);
    }
  }
}

function fillCard(node, t) {
  node.replaceChildren();
  const top = el("div", "flex items-center gap-2");
  top.append(el("span", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id));
  if (t.attempt > 0) {
    const retried = t.attempt > 1;
    top.append(el("span", `ml-auto rounded px-1.5 text-xs font-medium ${retried ? "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300" : "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300"}`, `attempt ${t.attempt}`));
  }
  node.append(top, el("h3", "mt-1 line-clamp-2 font-medium leading-snug", t.title));
  if (t.repeat) {
    const isRestart = t.repeat.kind === "restart_at_plan";
    node.append(el("p", `mt-2 rounded-md px-2 py-1 text-xs leading-snug ${isRestart ? "bg-fuchsia-50 text-fuchsia-800 dark:bg-fuchsia-400/10 dark:text-fuchsia-300" : "bg-amber-50 text-amber-800 dark:bg-amber-400/10 dark:text-amber-300"}`, `${isRestart ? "↩️ restarted at plan" : "🔁 repeat"}: ${t.repeat.reason}`));
  }
  if (t.hold_cause) {
    node.append(el("p", "mt-2 rounded-md bg-rose-50 px-2 py-1 text-xs leading-snug text-rose-800 dark:bg-rose-400/10 dark:text-rose-300", `⛔ ${t.hold_cause}`));
  }
  const foot = el("div", "mt-2 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400");
  const time = el("span", "whitespace-nowrap tabular-nums");
  time.dataset.since = t.step_started_at;
  time.dataset.prefix = t.column === "landed" ? "✅ " : "⏱ ";
  time.dataset.suffix = t.column === "landed" ? " ago" : "";
  foot.append(time);
  if (t.slot && !lanes) foot.append(el("span", "ml-auto whitespace-nowrap rounded bg-slate-100 px-1.5 font-mono dark:bg-slate-700", `🧩 ${t.slot}`));
  node.append(foot);
  if (STEPS.some((s) => s.id === t.column)) {
    const quiet = quietSpan(t.last_activity_at);
    node.append(quiet);
    tick(quiet);
  }
  tick(time);
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
          let node = cards.get(t.id);
          if (!node) {
            node = el("article", "relative cursor-pointer rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-sm transition-colors hover:border-indigo-300 data-[quiet-level=slow]:border-amber-400 data-[quiet-level=long]:border-rose-400 dark:border-slate-700/70 dark:bg-slate-800 dark:hover:border-indigo-400/60");
            node.addEventListener("click", () => openDrawer(t.id));
            cards.set(t.id, node);
          }
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
  $("summary").textContent = `${all.length} tasks · ${all.filter((t) => STEPS.some((s) => s.id === t.column)).length} running · ${all.filter((t) => t.column === "held").length} held`;
}

const viewButton = (active) => `rounded px-2.5 py-1 text-xs font-medium ${active ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`;

function setLanes(on) {
  const first = rects();
  lanes = on;
  $("view-columns").className = viewButton(!on);
  $("view-lanes").className = viewButton(on);
  buildBoard();
  renderBoard(first);
}

// ---------- drawer ----------

const attemptOf = () => open.detail.attempts.find((a) => a.step === open.step && a.n === open.n);

// Select an attempt: the given one, else the last of the step, else the last of the task.
function select(step, n) {
  const list = open.detail.attempts;
  const a = n != null ? list.find((x) => x.step === step && x.n === n) : list.findLast((x) => !step || x.step === step) ?? list.at(-1);
  open.step = a?.step;
  open.n = a?.n;
  renderDrawer();
}

async function openDrawer(id) {
  open = { id, detail: await source.detail(id) };
  select();
  $("drawer").classList.remove("translate-x-full");
  $("backdrop").classList.remove("pointer-events-none", "opacity-0");
}

function closeDrawer() {
  open = null;
  $("drawer").classList.add("translate-x-full");
  $("backdrop").classList.add("pointer-events-none", "opacity-0");
}

function renderDrawer() {
  if (!open) return;
  const { detail } = open;
  const t = tasks.get(open.id) || detail.task;
  const col = COLUMNS.find((c) => c.id === t.column);
  const f = detail.fields;
  const drawer = $("drawer");
  drawer.replaceChildren();

  const head = el("div", "flex items-start gap-3 px-6 pt-5");
  const title = el("div", "min-w-0 flex-1");
  const meta = [`${col.emoji} ${col.label}`, t.slot && `🧩 slot ${t.slot}`, f.priority, f.branch ?? "no task branch", `created ${ago(f.created_at)}`].filter(Boolean);
  title.append(
    el("p", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id),
    el("h2", "mt-0.5 text-xl font-semibold leading-snug", t.title),
    el("p", "mt-1.5 text-xs text-slate-500 dark:text-slate-400", meta.join("  ·  ")),
  );
  const close = el("button", "rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800", "✕");
  close.type = "button";
  close.title = "Close (Esc)";
  close.addEventListener("click", closeDrawer);
  head.append(title, close);
  drawer.append(head, el("p", "line-clamp-2 px-6 pt-3 text-sm text-slate-600 dark:text-slate-300", f.description));
  if (t.hold_cause) drawer.append(el("p", "mx-6 mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-400/10 dark:text-rose-300", `⛔ ${t.hold_cause}`));
  if (!detail.attempts.length) {
    drawer.append(el("p", "px-6 pt-5 text-sm text-slate-500", "Not started: no attempt yet."));
    return;
  }
  drawer.append(trail(t), attemptPanel());
  const tail = $("tail");
  if (tail) tail.scrollTop = tail.scrollHeight;
}

const JUMP = {
  repeat: { text: "↻ repeat", cls: "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300" },
  restart_at_plan: { text: "↩ back to plan", cls: "bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-400/15 dark:text-fuchsia-300" },
};

// Every attempt in the order it happened; a label between two nodes names a jump (repeat, back to plan) and the
// dashed nodes at the end are the steps still to come.
function trail(t) {
  const list = open.detail.attempts;
  const row = el("div", "flex flex-wrap items-center gap-x-1.5 gap-y-2 px-6 pt-5");
  const link = (a) => {
    const jump = a?.after && JUMP[a.after];
    const node = jump ? el("span", `rounded-full px-2 py-0.5 text-xs font-medium ${jump.cls}`, jump.text) : el("span", "text-slate-400", "→");
    if (jump) node.title = a.reason ?? "";
    return node;
  };
  list.forEach((a, i) => {
    if (i) row.append(link(a));
    const step = STEPS.find((s) => s.id === a.step);
    const on = open.step === a.step && open.n === a.n;
    const tone = a.state === "failed" ? "border-rose-300 dark:border-rose-400/50" : a.state === "running" ? "border-emerald-400 dark:border-emerald-400/60" : "border-slate-200 dark:border-slate-700";
    const node = el("button", `rounded-lg border px-2.5 py-1.5 text-left text-xs ${tone} ${on ? "ring-2 ring-indigo-400" : "hover:border-indigo-300 dark:hover:border-indigo-400/60"} ${a.state === "running" ? "bg-emerald-50/60 dark:bg-emerald-400/10" : "bg-white dark:bg-slate-800"}`);
    node.type = "button";
    node.title = a.summary;
    const dur = a.ended_at ? fmtDur(Date.parse(a.ended_at) - Date.parse(a.started_at)) : since(a.started_at);
    node.append(el("span", "block text-sm font-medium", `${step.emoji} ${step.label}`), el("span", "text-slate-500 dark:text-slate-400", `#${a.n} ${STATE[a.state].emoji} ${dur}`));
    node.addEventListener("click", () => select(a.step, a.n));
    row.append(node);
  });
  const last = list.at(-1);
  if (STEPS.some((s) => s.id === t.column) && last.state !== "failed") {
    for (const step of STEPS.slice(STEPS.findIndex((s) => s.id === last.step) + 1)) {
      row.append(el("span", "text-slate-300 dark:text-slate-600", "→"), el("span", "rounded-lg border border-dashed border-slate-300 px-2.5 py-1.5 text-sm text-slate-400 dark:border-slate-700 dark:text-slate-600", `${step.emoji} ${step.label}`));
    }
  }
  return row;
}

function quietSpan(since) {
  const node = el("span", "rounded px-1.5 text-xs font-medium");
  node.dataset.quiet = since;
  tick(node);
  return node;
}

function attemptPanel() {
  const a = attemptOf();
  const panel = el("div", "flex min-h-0 flex-1 flex-col gap-3 px-6 pb-6 pt-5");
  const step = STEPS.find((s) => s.id === open.step);
  const live = a.state === "running";
  const bar = el("div", `flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-sm ${STATE[a.state].cls}`);
  bar.append(
    el("span", "font-medium", `${step.emoji} ${step.label} · attempt ${a.n} · ${STATE[a.state].emoji} ${a.state}`),
    el("span", "text-xs opacity-80", `started ${ago(a.started_at)} · ${a.ended_at ? `ran ${fmtDur(Date.parse(a.ended_at) - Date.parse(a.started_at))}` : "still running"}`),
  );
  if (live) bar.append(quietSpan(a.feed.at(-1)?.at ?? a.started_at));
  else bar.append(el("span", "w-full", a.summary));
  if (a.after) bar.append(el("span", "w-full text-xs opacity-80", `${JUMP[a.after].text}${a.reason ? `: ${a.reason}` : ""}`));
  const head = el("h3", "flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500");
  head.append(live ? "Live tail" : "Last lines");
  if (live) head.append(el("span", "h-2 w-2 animate-pulse-dot rounded-full bg-emerald-500"));
  head.append(el("span", "ml-auto font-normal normal-case tracking-normal", "⏱ command ran · 🤔 agent thought before it"));
  const tail = el("div", "min-h-0 flex-1 space-y-1 overflow-y-auto rounded-lg bg-slate-50 p-2 dark:bg-slate-950/60");
  tail.id = "tail";
  if (!a.feed.length) tail.append(el("p", "p-2 text-sm text-slate-500", "No lines recorded for this attempt."));
  for (const e of a.feed) tail.append(feedLine(e));
  panel.append(bar, head, tail);
  return panel;
}

function feedLine(e) {
  const row = el("div", "animate-line-in rounded-md px-2 py-1 text-xs leading-snug");
  row.dataset.eid = e.id || "";
  const line = el("div", "flex items-start gap-2");
  const icon = el("span", "w-5 shrink-0 text-center");
  const body = el("span", "min-w-0 flex-1");
  const meta = el("span", "ml-auto flex shrink-0 gap-2 tabular-nums text-slate-500 dark:text-slate-400");
  if (e.type === "command") {
    const running = e.state === "running";
    const failed = !running && e.exit_code !== 0;
    if (e.waited_ms >= 2000) row.append(el("p", "mb-0.5 pl-7 text-[0.7rem] text-slate-400 dark:text-slate-500", `🤔 agent thought ${fmtDur(e.waited_ms)}`));
    icon.textContent = running ? "▶️" : failed ? "❌" : "⚙️";
    body.append(el("code", "block truncate font-mono text-[0.78rem]", e.cmd));
    if (running) {
      const t = el("span", "text-emerald-600 dark:text-emerald-400");
      t.dataset.since = e.at;
      t.dataset.prefix = "⏱ running ";
      tick(t);
      meta.append(t);
    } else {
      meta.append(el("span", failed ? "text-rose-600 dark:text-rose-400" : "", `⏱ ${fmtDur(e.duration_ms)}${failed ? ` · exit ${e.exit_code}` : ""}`));
    }
  } else if (e.type === "message") {
    icon.textContent = "💬";
    body.className = "min-w-0 flex-1 text-slate-700 dark:text-slate-300";
    body.textContent = e.text;
    row.classList.add("bg-indigo-50/70", "dark:bg-indigo-400/10");
  } else if (e.type === "check") {
    icon.textContent = e.passed ? "✅" : "❌";
    body.append(el("span", "font-medium", `check ${e.name} ${e.passed ? "passed" : "failed"}`));
    meta.append(el("span", "", `⏱ ${fmtDur(e.duration_ms)}`));
  } else {
    icon.textContent = "🚦";
    body.append(el("span", "text-slate-500 dark:text-slate-400", `entered ${e.step}, attempt ${e.attempt}`));
  }
  line.append(icon, body, meta);
  row.append(line);
  return row;
}

// Any agent line is activity: it resets the quiet time on the card and in the open drawer.
function onFeed(msg) {
  const e = msg.event;
  const task = tasks.get(msg.task_id);
  if (task) task.last_activity_at = e.at;
  for (const q of [cards.get(msg.task_id), $("drawer")]) {
    const span = q?.querySelector("[data-quiet]");
    if (span && (q !== $("drawer") || open?.id === msg.task_id)) {
      span.dataset.quiet = e.at;
      tick(span);
    }
  }
  if (!open || open.id !== msg.task_id) return;
  const attempt = open.detail.attempts.find((a) => a.step === msg.step && a.n === msg.attempt);
  if (!attempt) return;
  const at = e.id ? attempt.feed.findIndex((x) => x.id === e.id) : -1;
  if (at >= 0) attempt.feed[at] = e;
  else attempt.feed.push(e);
  attempt.feed = attempt.feed.slice(-FEED_LIMIT);
  const tail = $("tail");
  if (!tail || attemptOf() !== attempt) return;
  if (tail.firstChild?.tagName === "P") tail.replaceChildren();
  const line = feedLine(e);
  const old = e.id && [...tail.children].find((c) => c.dataset.eid === e.id);
  if (old) old.replaceWith(line);
  else tail.append(line);
  while (tail.children.length > FEED_LIMIT) tail.firstChild.remove();
  tail.scrollTo({ top: tail.scrollHeight, behavior: "smooth" });
}

// A card moved: the open task's attempts changed (one ended, one began), so reload its detail.
async function onTask(task) {
  tasks.set(task.id, task);
  renderBoard();
  if (open?.id !== task.id) return;
  const follow = attemptOf()?.state === "running" && attemptOf() === open.detail.attempts.at(-1);
  open.detail = await source.detail(open.id);
  if (follow || !attemptOf()) select();
  else renderDrawer();
}

// ---------- theme and start ----------

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
  $("backdrop").addEventListener("click", closeDrawer);
  $("view-columns").addEventListener("click", () => setLanes(false));
  $("view-lanes").addEventListener("click", () => setLanes(true));
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
  source = await mockSource();
  $("mode").textContent = `🧪 ${source.label}`;
  const snap = await source.snapshot();
  slotNames = snap.slots;
  for (const t of snap.tasks) tasks.set(t.id, t);
  setLanes(false);
  source.subscribe((msg) => (msg.kind === "feed" ? onFeed(msg) : onTask(msg.task)));
  setInterval(() => document.querySelectorAll("[data-since],[data-quiet]").forEach(tick), 1000);
}

start();
