// The task drawer: a rail of the task's attempts on the left, one selected attempt on the right
// (its lines, its result and the prompt it was given). Shapes: docs/design/dashboard-ui.md.

import { $, COLUMNS, FEED_LIMIT, JUMP, STATE, STEPS, ago, callout, clock, dot, el, fmtDur, quietSpan, since, tag, tick } from "./ui.js";

let source = null;
let tasks = null;
let open = null; // {id, detail, step, n, tab}: the open task, its selected attempt and sub-tab

export function initDrawer(src, taskMap) {
  source = src;
  tasks = taskMap;
  $("backdrop").addEventListener("click", closeDrawer);
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeDrawer(); });
}

const attemptOf = () => open.detail.attempts.find((a) => a.step === open.step && a.n === open.n);
const tabOf = (a) => open.tab ?? (a.state === "running" ? "lines" : "result");

// Select an attempt: the given one, else the last of the step, else the last of the task.
function select(step, n) {
  const list = open.detail.attempts;
  const a = n != null ? list.find((x) => x.step === step && x.n === n) : list.findLast((x) => !step || x.step === step) ?? list.at(-1);
  open.step = a?.step;
  open.n = a?.n;
  render();
}

export async function openDrawer(id) {
  open = { id, detail: await source.detail(id), tab: null, view: null };
  select();
  $("drawer").classList.remove("translate-x-full");
  $("backdrop").classList.remove("pointer-events-none", "opacity-0");
}

export function closeDrawer() {
  open = null;
  $("drawer").classList.add("translate-x-full");
  $("backdrop").classList.add("pointer-events-none", "opacity-0");
}

const VIEWS = [["attempts", "Attempts"], ["task", "Task"]];

function render() {
  if (!open) return;
  const { detail } = open;
  const t = tasks.get(open.id) || detail.task;
  const col = COLUMNS.find((c) => c.id === t.column);
  const view = open.view ?? (detail.attempts.length ? "attempts" : "task");
  const drawer = $("drawer");
  drawer.replaceChildren();

  const head = el("header", "flex items-start gap-4 px-6 pb-3 pt-5");
  const title = el("div", "min-w-0 flex-1");
  const status = el("div", "flex items-center gap-2");
  status.append(el("span", "font-mono text-xs text-slate-500 dark:text-slate-400", t.id), tag(`${col.emoji} ${col.label}`, { cls: "text-slate-700 dark:text-slate-200" }), ...(t.slot ? [tag(`slot ${t.slot}`, { cls: "font-mono" })] : []), el("span", "truncate text-xs text-slate-500 dark:text-slate-400", col.help));
  title.append(status, el("h2", "mt-1.5 text-lg font-semibold leading-snug", t.title));
  const close = el("button", "rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800", "Close");
  close.type = "button";
  close.addEventListener("click", closeDrawer);
  head.append(title, close);
  drawer.append(head);
  if (t.hold_cause) {
    const hold = el("div", "px-6 pb-3");
    hold.append(callout("border-rose-500", "Held", t.hold_cause));
    drawer.append(hold);
  }

  const bar = el("div", "flex gap-5 border-b border-slate-200 px-6 dark:border-slate-800");
  const counts = { attempts: detail.attempts.length };
  for (const [id, label] of VIEWS) {
    const on = id === view;
    const b = el("button", `-mb-px border-b-2 pb-2 text-sm ${on ? "border-slate-900 font-semibold dark:border-slate-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, counts[id] ? `${label} ${counts[id]}` : label);
    b.type = "button";
    b.addEventListener("click", () => { open.view = id; render(); });
    bar.append(b);
  }
  drawer.append(bar);

  if (view === "task") return drawer.append(taskView(detail));
  if (!detail.attempts.length) return drawer.append(el("p", "px-6 py-5 text-sm text-slate-500", "Not started: no attempt yet."));
  const body = el("div", "flex min-h-0 flex-1");
  body.append(rail(t), pane());
  drawer.append(body);
  body.querySelector("[data-selected]")?.scrollIntoView({ block: "nearest" });
  const tail = $("tail");
  if (tail) tail.scrollTop = tail.scrollHeight;
}

// ---------- the task as the tracker holds it ----------

const prose = (text) => el("div", "whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200", text);
const section = (title, text) => {
  const node = el("section");
  node.append(el("h4", "mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500", title), prose(text));
  return node;
};

// The task as the tracker holds it: its text and the discussion on the left, its metadata in a sidebar on the right.
function taskView({ fields: f, comments }) {
  const wrap = el("div", "flex min-h-0 flex-1");
  const main = el("div", "flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5");
  main.append(section("Description", f.description));
  for (const [title, text] of [["Acceptance criteria", f.acceptance], ["Design", f.design], ["Notes", f.notes]]) if (text) main.append(section(title, text));
  const thread = el("section", "border-t border-slate-200 pt-5 dark:border-slate-800");
  thread.append(el("h4", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", `Comments · ${comments.length}`));
  if (!comments.length) thread.append(el("p", "text-sm text-slate-500", "No comments on this task."));
  for (const c of comments) {
    const item = el("article", "mb-4 border-l-2 border-slate-200 pl-3 dark:border-slate-700");
    const who = el("div", "mb-1 flex items-center gap-2 text-xs");
    who.append(tag(c.author, { cls: c.author === "factory" ? "text-indigo-700 dark:text-indigo-300" : "text-slate-700 dark:text-slate-200" }), el("span", "text-slate-500 dark:text-slate-400", ago(c.at)));
    item.append(who, prose(c.text));
    thread.append(item);
  }
  main.append(thread);
  const side = el("aside", "w-60 shrink-0 overflow-y-auto border-l border-slate-200 px-5 py-5 dark:border-slate-800");
  const props = el("dl", "flex flex-col gap-4 text-xs");
  for (const [k, v] of [["Priority", f.priority], ["Labels", f.labels.join(", ")], ["Task branch", f.branch], ["Claim", f.claimed_by], ["Depends on", f.depends_on.join(", ")], ["Created", ago(f.created_at)], ["Updated", ago(f.updated_at)]]) {
    const item = el("div", "min-w-0");
    item.append(el("dt", "text-slate-500 dark:text-slate-400", k), el("dd", "mt-0.5 break-words font-medium", v || "none"));
    props.append(item);
  }
  side.append(el("h4", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", "Details"), props);
  wrap.append(main, side);
  return wrap;
}

// ---------- rail ----------

// Newest first, so the attempt that is running now is at the top when the drawer opens. A jump label sits under the
// attempt it began, between it and the one before; steps still to come are dim rows above.
function rail(t) {
  const list = open.detail.attempts;
  const wrap = el("nav", "w-64 shrink-0 overflow-y-auto border-r border-slate-200 px-4 py-4 dark:border-slate-800");
  wrap.append(el("h3", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", `Attempts · ${list.length} · newest first`));
  const ol = el("ol", "ml-1 border-l border-slate-200 dark:border-slate-700");
  const last = list.at(-1);
  if (STEPS.some((s) => s.id === t.column) && last.state !== "failed") {
    for (const s of STEPS.slice(STEPS.findIndex((x) => x.id === last.step) + 1).reverse()) {
      const li = el("li", "relative py-1.5 pl-4 text-[13px] text-slate-400 dark:text-slate-600");
      li.append(el("span", "absolute -left-[3px] top-[0.8rem] h-1.5 w-1.5 rounded-full border border-slate-300 dark:border-slate-600"), `${s.emoji} ${s.label}`);
      ol.append(li);
    }
  }
  for (let i = list.length - 1; i >= 0; i--) {
    ol.append(railRow(list[i]));
    if (list[i].after) ol.append(jump(list[i], list[i - 1]));
  }
  wrap.append(ol);
  return wrap;
}

function jump(a, prev) {
  const j = JUMP[a.after];
  const li = el("li", `relative pb-0.5 pl-4 pt-1.5 text-[11px] leading-snug ${j.text}`);
  li.title = a.reason ?? "";
  li.append(el("span", "font-medium", `${j.glyph} ${j.label}`));
  if (a.reason && a.reason !== prev?.summary) li.append(el("span", "block line-clamp-2 text-slate-500 dark:text-slate-400", a.reason));
  return li;
}

function railRow(a) {
  const st = STATE[a.state];
  const selected = open.step === a.step && open.n === a.n;
  const li = el("li", "relative pl-3");
  const dotEl = dot(st.dot);
  dotEl.classList.add("absolute", "-left-[3px]", "top-[0.95rem]");
  const btn = el("button", `block w-full rounded px-2 py-1.5 text-left ${selected ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"}`);
  btn.type = "button";
  if (selected) btn.dataset.selected = "1";
  const dur = a.ended_at ? fmtDur(Date.parse(a.ended_at) - Date.parse(a.started_at)) : since(a.started_at);
  const row = el("span", "flex items-baseline gap-2");
  row.append(
    el("span", `text-[13px] ${selected ? "font-semibold" : "font-medium"}`, `${STEPS.find((s) => s.id === a.step).emoji} ${STEPS.find((s) => s.id === a.step).label}`),
    el("span", "text-[11px] text-slate-500 dark:text-slate-400", `#${a.n}`),
    el("span", "ml-auto text-[11px] tabular-nums text-slate-500 dark:text-slate-400", dur),
  );
  btn.append(row);
  if (a.state === "failed") btn.append(el("span", "mt-0.5 block truncate text-[11px] text-slate-500 dark:text-slate-400", a.summary));
  btn.addEventListener("click", () => select(a.step, a.n));
  li.append(dotEl, btn);
  return li;
}

// ---------- selected attempt ----------

const TABS = [["lines", "Lines"], ["result", "Result"], ["prompt", "Prompt"]];

function pane() {
  const a = attemptOf();
  const st = STATE[a.state];
  const tab = tabOf(a);
  const wrap = el("section", "flex min-w-0 flex-1 flex-col");
  const head = el("div", "flex flex-wrap items-center gap-x-3 gap-y-1 px-6 pt-4");
  head.append(el("h3", "text-sm font-semibold", `${STEPS.find((s) => s.id === a.step).emoji} ${STEPS.find((s) => s.id === a.step).label}, attempt ${a.n}`), tag(st.label, { dotCls: st.dot, cls: st.text }));
  const timing = a.ended_at ? `ran ${fmtDur(Date.parse(a.ended_at) - Date.parse(a.started_at))}` : "still running";
  head.append(el("span", "text-xs text-slate-500 dark:text-slate-400", `started ${ago(a.started_at)}, ${timing}`));
  if (a.state === "running") head.append(quietSpan(a.feed.at(-1)?.at ?? a.started_at));
  wrap.append(head);
  if (a.after) {
    const why = el("div", "px-6 pt-3");
    const prev = open.detail.attempts[open.detail.attempts.indexOf(a) - 1];
    const what = a.after === "repeat" ? "Repeat of" : "Back to plan after";
    why.append(callout(JUMP[a.after].bar, `${what} ${STEPS.find((s) => s.id === prev.step).label} #${prev.n}`, a.reason));
    wrap.append(why);
  }

  const bar = el("div", "mt-3 flex gap-5 border-b border-slate-200 px-6 dark:border-slate-800");
  for (const [id, label] of TABS) {
    const on = id === tab;
    const count = id === "lines" ? ` ${a.feed.length}` : "";
    const b = el("button", `-mb-px border-b-2 pb-2 text-[13px] ${on ? "border-slate-900 font-semibold dark:border-slate-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, `${label}${count}`);
    b.type = "button";
    b.addEventListener("click", () => { open.tab = id; render(); });
    bar.append(b);
  }
  wrap.append(bar, tab === "lines" ? lines(a) : tab === "result" ? result(a) : prompt(a));
  return wrap;
}

const BLOCK = "min-h-0 flex-1 overflow-y-auto px-6 py-4";

function lines(a) {
  const box = el("div", BLOCK);
  box.id = "tail";
  const head = el("p", "mb-2 flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400");
  head.append(a.state === "running" ? "Live tail" : "Last lines", el("span", "ml-auto", "Offset from attempt start  ·  agent thought time shown before a command"));
  const list = el("div", "divide-y divide-slate-100 dark:divide-slate-800/70");
  list.id = "lines";
  if (!a.feed.length) list.append(el("p", "py-3 text-sm text-slate-500", "No lines recorded for this attempt."));
  for (const e of a.feed) list.append(line(e, a));
  box.append(head, list);
  return box;
}

const KIND = { command: "CMD", message: "MSG", check: "CHECK", step: "STEP" };

// One row of the log grid: offset, kind, content, duration. An "agent thought" hint sits above the command it led to.
function line(e, a) {
  const hint = e.type === "command" && e.waited_ms >= 2000;
  const row = el("div", "animate-line-in grid grid-cols-[3.25rem_3.25rem_minmax(0,1fr)_auto] items-baseline gap-x-3 py-1.5 text-xs");
  row.dataset.eid = e.id || "";
  if (hint) row.append(el("span", "col-start-3 row-start-1 mb-0.5 text-[11px] text-slate-400 dark:text-slate-500", `agent thought ${fmtDur(e.waited_ms)}`));
  const at = el("span", `${hint ? "col-start-1 row-start-2" : "col-start-1 row-start-1"} font-mono tabular-nums text-slate-400 dark:text-slate-500`, clock(Date.parse(e.at) - Date.parse(a.started_at)));
  const kind = el("span", `${hint ? "col-start-2 row-start-2" : "col-start-2 row-start-1"} text-[10px] font-semibold tracking-wider text-slate-400 dark:text-slate-500`, KIND[e.type]);
  const content = el("span", `${hint ? "col-start-3 row-start-2" : "col-start-3 row-start-1"} min-w-0`);
  const right = el("span", `${hint ? "col-start-4 row-start-2" : "col-start-4 row-start-1"} text-right tabular-nums text-slate-500 dark:text-slate-400`);
  if (e.type === "command") {
    const running = e.state === "running";
    const failed = !running && e.exit_code !== 0;
    content.append(el("code", "block truncate font-mono text-[12px]", e.cmd));
    if (running) {
      right.dataset.since = e.at;
      right.dataset.prefix = "running ";
      right.className += " text-sky-600 dark:text-sky-400";
      tick(right);
    } else {
      right.textContent = `${fmtDur(e.duration_ms)}${failed ? `  exit ${e.exit_code}` : ""}`;
      if (failed) right.className += " font-medium text-rose-600 dark:text-rose-400";
    }
  } else if (e.type === "message") {
    content.className += " text-slate-700 dark:text-slate-200";
    content.textContent = e.text;
  } else if (e.type === "check") {
    content.append(el("span", "font-mono text-[12px]", e.name), "  ", el("span", `font-medium ${e.passed ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`, e.passed ? "passed" : "failed"));
    right.textContent = fmtDur(e.duration_ms);
  } else {
    content.append(el("span", "text-slate-500 dark:text-slate-400", `attempt ${e.attempt} of ${e.step} started`));
  }
  row.append(at, kind, content, right);
  return row;
}

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

// ---------- live updates ----------

// Any agent line is activity: it resets the quiet time on the card and in the open drawer.
export function onFeed(msg) {
  const e = msg.event;
  const task = tasks.get(msg.task_id);
  if (task) task.last_activity_at = e.at;
  document.querySelector(`[data-id="${msg.task_id}"] [data-quiet]`)?.setAttribute("data-quiet", e.at);
  if (!open || open.id !== msg.task_id) return;
  const attempt = open.detail.attempts.find((a) => a.step === msg.step && a.n === msg.attempt);
  if (!attempt) return;
  const at = e.id ? attempt.feed.findIndex((x) => x.id === e.id) : -1;
  if (at >= 0) attempt.feed[at] = e;
  else attempt.feed.push(e);
  attempt.feed = attempt.feed.slice(-FEED_LIMIT);
  const drawerQuiet = $("drawer").querySelector("[data-quiet]");
  if (drawerQuiet) drawerQuiet.dataset.quiet = e.at;
  const list = $("lines");
  if (!list || attemptOf() !== attempt) return;
  if (list.firstChild?.tagName === "P") list.replaceChildren();
  const row = line(e, attempt);
  const old = e.id && [...list.children].find((c) => c.dataset.eid === e.id);
  if (old) old.replaceWith(row);
  else list.append(row);
  while (list.children.length > FEED_LIMIT) list.firstChild.remove();
  const box = $("tail");
  box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
}

// A card moved: the open task's attempts changed (one ended, one began), so reload its detail.
export async function onTaskMoved(task) {
  if (open?.id !== task.id) return;
  const follow = attemptOf()?.state === "running" && attemptOf() === open.detail.attempts.at(-1);
  open.detail = await source.detail(open.id);
  if (follow || !attemptOf()) {
    open.tab = null;
    select();
  } else render();
}
