// Task loop dashboard page. Plain ES module, no framework, no build step.
// The page consumes the shapes in docs/design/dashboard-ui.md. Only mock mode exists so far:
// `mockSource` turns fixtures.json into those shapes and replays events on a timer.

const COLUMNS = [
  { id: "waiting", label: "Waiting", emoji: "⏳", bar: "bg-slate-400" },
  { id: "plan", label: "Plan", emoji: "🧭", bar: "bg-sky-500" },
  { id: "implement", label: "Implement", emoji: "🛠️", bar: "bg-indigo-500" },
  { id: "checks", label: "Checks", emoji: "🧪", bar: "bg-violet-500" },
  { id: "land", label: "Land", emoji: "🚀", bar: "bg-teal-500" },
  { id: "held", label: "Held", emoji: "⛔", bar: "bg-rose-500" },
  { id: "landed", label: "Landed", emoji: "✅", bar: "bg-emerald-500" },
];
const FEED_LIMIT = 20;

const tasks = new Map(); // id -> board card
const feeds = new Map(); // id -> live events, oldest first
const details = new Map(); // id -> {fields, attempts}
const cards = new Map(); // id -> element
const columnEls = new Map(); // column id -> {body, count}
let openId = null;
let source = null;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

// ---------- formatting ----------

function fmtDur(ms) {
  if (ms < 1000) return `${Math.max(ms, 0)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(Math.floor(s % 60)).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
const since = (iso) => fmtDur(Date.now() - Date.parse(iso));
const ago = (iso) => `${since(iso)} ago`;

// ---------- mock source ----------

async function mockSource() {
  const fx = await (await fetch("fixtures.json")).json();
  const iso = (agoS) => new Date(Date.now() - agoS * 1000).toISOString();
  const card = (t) => ({
    id: t.id, title: t.title, column: t.column, attempt: t.attempt, repeat: t.repeat,
    step_started_at: iso(t.step_started_ago_s), last_activity_at: iso(t.last_activity_ago_s),
    slot: t.slot, hold_cause: t.hold_cause,
  });
  const event = (e) => {
    const { ago_s, ...rest } = e;
    return { ...rest, at: iso(ago_s) };
  };
  const snapshot = { generated_at: new Date().toISOString(), tasks: fx.tasks.map(card) };
  const detail = {};
  for (const t of fx.tasks) {
    const { created_ago_s, ...fields } = t.fields;
    detail[t.id] = {
      task: card(t),
      fields: { ...fields, created_at: iso(created_ago_s) },
      attempts: (fx.attempts[t.id] || []).map(({ ago_s, ...a }) => ({ ...a, started_at: iso(ago_s) })),
      feed: (fx.feeds[t.id] || []).map(event).slice(-FEED_LIMIT),
    };
  }
  return {
    label: "mock data",
    snapshot: async () => snapshot,
    detail: async (id) => detail[id],
    subscribe(on) {
      const current = new Map(snapshot.tasks.map((t) => [t.id, t]));
      for (const step of fx.script) {
        setTimeout(() => {
          if (step.kind === "feed") return on({ kind: "feed", task_id: step.task_id, event: { ...step.event, at: new Date().toISOString() } });
          const { step_started_ago_s = 0, ...patch } = step.task;
          const next = { ...current.get(step.task.id), ...patch };
          next.step_started_at = iso(step_started_ago_s);
          next.last_activity_at = new Date().toISOString();
          current.set(next.id, next);
          on({ kind: "task", task: next });
        }, step.after_s * 1000);
      }
    },
  };
}

// ---------- board ----------

function buildBoard() {
  const board = $("board");
  for (const col of COLUMNS) {
    const section = el("section", "flex min-h-0 min-w-0 flex-col rounded-xl bg-slate-200/50 dark:bg-slate-900/60");
    const head = el("div", "flex items-center gap-2 px-3 pt-3 pb-2");
    head.append(el("span", `h-2 w-2 rounded-full ${col.bar}`), el("h2", "text-sm font-semibold", `${col.emoji} ${col.label}`));
    const count = el("span", "ml-auto rounded-full bg-white px-2 text-xs tabular-nums text-slate-500 dark:bg-slate-800 dark:text-slate-400", "0");
    head.append(count);
    const body = el("div", "flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2");
    section.append(head, body);
    board.append(section);
    columnEls.set(col.id, { body, count });
  }
}

function buildCard(id) {
  const node = el("article", "relative cursor-pointer rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-sm transition-colors hover:border-indigo-300 dark:border-slate-700/70 dark:bg-slate-800 dark:hover:border-indigo-400/60");
  node.dataset.id = id;
  node.addEventListener("click", () => openDrawer(id));
  return node;
}

function fillCard(node, t) {
  const col = COLUMNS.find((c) => c.id === t.column);
  node.replaceChildren();
  const top = el("div", "flex items-center gap-2");
  top.append(el("span", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id));
  if (t.attempt > 0) {
    const retried = t.attempt > 1;
    top.append(el("span", `ml-auto rounded px-1.5 text-xs font-medium ${retried ? "bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300" : "bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300"}`, `attempt ${t.attempt}`));
  }
  node.append(top, el("h3", "mt-1 line-clamp-2 font-medium leading-snug", t.title));
  if (t.repeat) {
    const isReplan = t.repeat.kind === "replan";
    const box = el("p", `mt-2 rounded-md px-2 py-1 text-xs leading-snug ${isReplan ? "bg-fuchsia-50 text-fuchsia-800 dark:bg-fuchsia-400/10 dark:text-fuchsia-300" : "bg-amber-50 text-amber-800 dark:bg-amber-400/10 dark:text-amber-300"}`);
    box.textContent = `${isReplan ? "🧭 replan" : "🔁 repeat"}: ${t.repeat.reason}`;
    node.append(box);
  }
  if (t.hold_cause) {
    node.append(el("p", "mt-2 rounded-md bg-rose-50 px-2 py-1 text-xs leading-snug text-rose-800 dark:bg-rose-400/10 dark:text-rose-300", `⛔ ${t.hold_cause}`));
  }
  const foot = el("div", "mt-2 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400");
  const time = el("span", "tabular-nums");
  time.dataset.since = t.step_started_at;
  time.dataset.prefix = t.column === "landed" ? "✅ " : "⏱ ";
  time.dataset.suffix = t.column === "landed" ? " ago" : "";
  foot.append(time);
  if (t.slot) foot.append(el("span", "ml-auto whitespace-nowrap rounded bg-slate-100 px-1.5 font-mono dark:bg-slate-700", `🧩 ${t.slot.replace("slot-", "")}`));
  node.append(foot);
  tick(time);
}

function renderBoard() {
  const first = new Map([...cards].map(([id, node]) => [id, node.getBoundingClientRect()]));
  for (const col of COLUMNS) {
    const inCol = [...tasks.values()]
      .filter((t) => t.column === col.id)
      .sort((a, b) => Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at));
    const { body, count } = columnEls.get(col.id);
    count.textContent = String(inCol.length);
    inCol.forEach((t, i) => {
      let node = cards.get(t.id);
      if (!node) {
        node = buildCard(t.id);
        cards.set(t.id, node);
      }
      fillCard(node, t);
      if (body.children[i] !== node) body.insertBefore(node, body.children[i] || null);
    });
  }
  for (const [id, node] of cards) {
    const before = first.get(id);
    const after = node.getBoundingClientRect();
    if (!before) continue;
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
  const held = [...tasks.values()].filter((t) => t.column === "held").length;
  const active = [...tasks.values()].filter((t) => ["plan", "implement", "checks", "land"].includes(t.column)).length;
  $("summary").textContent = `${tasks.size} tasks · ${active} in flight · ${held} held`;
}

function tick(node) {
  node.textContent = `${node.dataset.prefix || ""}${since(node.dataset.since)}${node.dataset.suffix || ""}`;
}

// ---------- drawer ----------

function field(label, value) {
  const wrap = el("div", "min-w-0");
  wrap.append(el("dt", "text-xs text-slate-500 dark:text-slate-400", label), el("dd", "truncate text-sm", value ?? "—"));
  return wrap;
}

async function openDrawer(id) {
  openId = id;
  const d = await source.detail(id);
  if (openId !== id) return;
  details.set(id, d);
  if (!feeds.has(id)) feeds.set(id, d.feed.slice());
  renderDrawer();
  $("drawer").classList.remove("translate-x-full");
  $("backdrop").classList.remove("pointer-events-none", "opacity-0");
}

function closeDrawer() {
  openId = null;
  $("drawer").classList.add("translate-x-full");
  $("backdrop").classList.add("pointer-events-none", "opacity-0");
}

function renderDrawer() {
  const t = tasks.get(openId);
  const d = details.get(openId);
  if (!t || !d) return;
  const col = COLUMNS.find((c) => c.id === t.column);
  const drawer = $("drawer");
  drawer.replaceChildren();
  const head = el("div", "flex items-start gap-3 border-b border-slate-200 p-5 dark:border-slate-800");
  const title = el("div", "min-w-0 flex-1");
  title.append(el("p", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id), el("h2", "mt-0.5 text-lg font-semibold leading-snug", t.title));
  const close = el("button", "rounded-md px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800", "✕");
  close.type = "button";
  close.title = "Close (Esc)";
  close.addEventListener("click", closeDrawer);
  head.append(title, close);

  const scroller = el("div", "flex min-h-0 flex-1 flex-col gap-4 p-5");
  const status = el("div", "flex flex-wrap gap-2 text-xs");
  status.append(el("span", "rounded-full bg-slate-100 px-2.5 py-1 font-medium dark:bg-slate-800", `${col.emoji} ${col.label}`));
  if (t.slot) status.append(el("span", "rounded-full bg-slate-100 px-2.5 py-1 font-mono dark:bg-slate-800", `🧩 ${t.slot}`));
  if (t.attempt) status.append(el("span", "rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800", `attempt ${t.attempt}`));
  if (t.repeat) status.append(el("span", "rounded-full bg-amber-100 px-2.5 py-1 text-amber-800 dark:bg-amber-400/15 dark:text-amber-300", `${t.repeat.kind === "replan" ? "🧭 replan" : "🔁 repeat"}: ${t.repeat.reason}`));
  scroller.append(status);
  if (t.hold_cause) scroller.append(el("p", "rounded-lg bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-400/10 dark:text-rose-300", `⛔ ${t.hold_cause}`));

  const f = d.fields;
  const grid = el("dl", "grid grid-cols-3 gap-x-4 gap-y-3");
  grid.append(field("Priority", f.priority), field("Branch", f.branch), field("Claimed by", f.claimed_by),
    field("Labels", (f.labels || []).join(", ")), field("Created", ago(f.created_at)), field("Time in step", since(t.step_started_at)));
  scroller.append(grid, el("p", "line-clamp-3 text-sm leading-relaxed text-slate-600 dark:text-slate-300", f.description));

  if (d.attempts.length) {
    const list = el("ol", "space-y-1 text-xs");
    for (const a of d.attempts) list.append(el("li", "flex gap-2 text-slate-600 dark:text-slate-300", `#${a.n} ${a.step} · ${ago(a.started_at)} · ${a.result}`));
    scroller.append(el("h3", "text-xs font-semibold uppercase tracking-wide text-slate-500", "Attempts"), list);
  }

  const live = ["plan", "implement", "checks", "land"].includes(t.column);
  const tailHead = el("h3", "flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500");
  tailHead.append("Live tail");
  tailHead.append(el("span", "ml-auto font-normal normal-case tracking-normal", "⏱ ran · ⌛ waited before"));
  if (live) tailHead.append(el("span", "h-2 w-2 animate-pulse-dot rounded-full bg-emerald-500"));
  const tail = el("div", "min-h-0 flex-1 space-y-1 overflow-y-auto rounded-lg bg-slate-50 p-2 dark:bg-slate-950/60");
  tail.id = "tail";
  scroller.append(tailHead, tail);
  drawer.append(head, scroller);
  const lines = feeds.get(openId) || [];
  if (!lines.length) tail.append(el("p", "p-2 text-sm text-slate-500", "No agent activity for this task yet."));
  for (const e of lines) tail.append(feedLine(e));
  tail.scrollTop = tail.scrollHeight;
}

function feedLine(e) {
  const row = el("div", "animate-line-in flex items-start gap-2 rounded-md px-2 py-1 text-xs leading-snug");
  row.dataset.eid = e.id || "";
  const icon = el("span", "w-5 shrink-0 text-center");
  const body = el("span", "min-w-0 flex-1");
  const meta = el("span", "ml-auto flex shrink-0 gap-2 tabular-nums text-slate-500 dark:text-slate-400");
  if (e.type === "command") {
    const running = e.state === "running";
    const failed = !running && e.exit_code !== 0;
    icon.textContent = running ? "▶️" : failed ? "❌" : "⚙️";
    body.append(el("code", "block truncate font-mono text-[0.78rem]", e.cmd));
    if (running) {
      const t = el("span", "text-emerald-600 dark:text-emerald-400");
      t.dataset.since = e.at;
      t.dataset.prefix = "⏱ running ";
      tick(t);
      meta.append(t);
    } else {
      meta.append(el("span", failed ? "text-rose-600 dark:text-rose-400" : "", `⏱ ${fmtDur(e.duration_ms)}`));
    }
    if (e.waited_ms != null) meta.append(el("span", "w-14 text-right opacity-70", `⌛ ${fmtDur(e.waited_ms)}`));
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
  row.append(icon, body, meta);
  return row;
}

function onFeed(id, e) {
  const list = feeds.get(id) || [];
  const at = e.id ? list.findIndex((x) => x.id === e.id) : -1;
  if (at >= 0) list[at] = e;
  else list.push(e);
  feeds.set(id, list.slice(-FEED_LIMIT));
  if (id !== openId) return;
  const tail = $("tail");
  if (!tail) return;
  if (tail.firstChild && !tail.firstChild.dataset.eid && tail.firstChild.tagName === "P") tail.replaceChildren();
  const line = feedLine(e);
  const old = e.id && [...tail.children].find((c) => c.dataset.eid === e.id);
  if (old) old.replaceWith(line);
  else tail.append(line);
  while (tail.children.length > FEED_LIMIT) tail.firstChild.remove();
tail.scrollTo({ top: tail.scrollHeight, behavior: "smooth" });
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
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
  source = await mockSource();
  $("mode").textContent = `🧪 ${source.label}`;
  buildBoard();
  const snap = await source.snapshot();
  for (const t of snap.tasks) tasks.set(t.id, t);
  renderBoard();
  source.subscribe((msg) => {
    if (msg.kind === "feed") return onFeed(msg.task_id, msg.event);
    tasks.set(msg.task.id, msg.task);
    renderBoard();
    if (openId === msg.task.id) renderDrawer();
  });
  setInterval(() => document.querySelectorAll("[data-since]").forEach(tick), 1000);
}

start();
