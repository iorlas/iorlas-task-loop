// The step rail of the drawer: the task's steps top to bottom in the order they happened (plan, implement, checks, land), each with
// its own try number, the idle time between two steps, and a repeat named as a repeat with its reason. A step and a try are two
// things: "step 2 of 4" is where the task is, "try 2" is how often that step ran.

import { JUMP, LAND, STATE, STEPS, VERIFY, dot, el, fmtDur, since, startedAt, stepInfo, tick } from "./ui.js";

const GAP_MS = 5000; // idle time shorter than this is not shown
const stepOf = stepInfo;

// How long an attempt ran, or has been running; an attempt the stores gave no start or end shows a dash.
export function lasted(a) {
  if (a.step === VERIFY.id) return "—"; // the factory stores no start or end of a verification
  if (!a.started_at) return "—";
  if (a.ended_at) return fmtDur(Date.parse(a.ended_at) - Date.parse(a.started_at));
  return a.state === "running" ? since(a.started_at) : "—";
}

const marker = (cls) => el("span", `absolute -left-[3px] top-[0.8rem] h-1.5 w-1.5 rounded-full border ${cls}`);

function idle(prev, next) {
  if (!prev?.ended_at || !next.started_at) return null;
  const ms = Date.parse(next.started_at) - Date.parse(prev.ended_at);
  if (ms < GAP_MS) return null;
  const li = el("li", "relative py-1 pl-4 text-[11px] text-slate-400 dark:text-slate-500", `⏸ idle ${fmtDur(ms)}`);
  li.title = "Time between the recorded end of the step above and the recorded start of this one; both are approximate.";
  return li;
}

// A repeat names the try it repeats (`repeat_of`, a try of the same step); a restart at plan names the step it follows in the chain.
function jump(a, list, i, select) {
  const j = JUMP[a.after];
  const prev = a.after === "repeat" ? list.find((x) => x.step === a.step && x.n === a.repeat_of) : list.slice(0, i).findLast((x) => x.step !== VERIFY.id);
  const li = el("li", `relative pb-0.5 pl-4 pt-1.5 text-[11px] leading-snug ${j.text}`);
  li.title = a.reason ?? "";
  const what = a.after === "repeat" ? `${j.glyph} ${j.label} of ${stepOf(prev?.step ?? a.step).label}${prev ? `, try ${prev.n}` : ""}` : `${j.glyph} ${j.label} after ${stepOf(prev?.step ?? a.step).label}${prev ? `, try ${prev.n}` : ""},${startedAt(a.started_at)}`;
  li.append(el("span", "font-medium", what));
  if (a.reason) li.append(el("span", "block line-clamp-2 text-slate-500 dark:text-slate-400", a.reason));
  if (a.led_by) li.append(causeLink(a, select));
  return li;
}

// A repeat of an agent attempt names what led to it: the failed verification, one click away.
export function causeLink(a, select) {
  const btn = el("button", "block text-left text-[11px] underline decoration-dotted underline-offset-2 hover:decoration-solid", `because of ${VERIFY.label}, try ${a.led_by} →`);
  btn.type = "button";
  btn.addEventListener("click", () => select(VERIFY.id, a.led_by));
  return btn;
}

function row(a, selected, select) {
  const st = STATE[a.state];
  const li = el("li", "relative pl-3");
  const dotEl = dot(st.dot);
  dotEl.classList.add("absolute", "-left-[3px]", "top-[0.95rem]");
  const btn = el("button", `block w-full rounded px-2 py-1.5 text-left ${selected ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"}`);
  btn.type = "button";
  if (selected) btn.dataset.selected = "1";
  const top = el("span", "flex items-baseline gap-2");
  top.append(
    el("span", `text-[13px] ${selected ? "font-semibold" : "font-medium"}`, `${stepOf(a.step).emoji} ${stepOf(a.step).label}`),
    el("span", "text-[11px] text-slate-500 dark:text-slate-400", `try ${a.n}`),
    el("span", "ml-auto text-[11px] tabular-nums text-slate-500 dark:text-slate-400", lasted(a)),
  );
  btn.append(top);
  if (a.state === "failed" || a.step === VERIFY.id) btn.append(el("span", "mt-0.5 block truncate text-[11px] text-slate-500 dark:text-slate-400", a.summary));
  btn.addEventListener("click", () => select(a.step, a.n));
  li.append(dotEl, btn);
  return li;
}

// The land is not an attempt of its own in the history yet: its row is the card's state (still to come, waiting for the person,
// landing, landed), after the idle time since the checks ended while it waits.
function landRow(t, last) {
  const here = t.column === "land" || t.column === "landed";
  const word = t.column === "landed" ? LAND.done : here ? LAND[t.land ?? "waiting"] : null;
  const li = el("li", `relative py-1.5 pl-4 ${here ? "" : "text-slate-400 dark:text-slate-600"}`);
  li.append(marker(t.column === "landed" ? "border-emerald-500 bg-emerald-500" : here ? "border-amber-500" : "border-slate-300 dark:border-slate-600"), el("span", `text-[13px] ${here ? "font-medium" : ""}`, `${STEPS.at(-1).emoji} ${STEPS.at(-1).label}`));
  if (!word) return li.append(el("span", "ml-2 text-[11px]", "pending")), li;
  li.append(el("span", `block text-[11px] ${word.text}`, word.row));
  if (t.column === "land" && t.land !== "landing") li.append(el("code", "block truncate font-mono text-[11px] text-slate-500 dark:text-slate-400", `tl step land ${t.id}`));
  if (t.column === "land" && last?.ended_at) {
    const idle = el("span", "block text-[11px] text-slate-400 dark:text-slate-500");
    [idle.dataset.prefix, idle.dataset.suffix, idle.dataset.since] = ["⏸ idle ", " since the checks ended", last.ended_at];
    tick(idle);
    li.append(idle);
  }
  return li;
}

// Every step of the chain in order: what ran (with its tries and the idle time between), then what has not started (pending), the land last.
export function rail(list, t, selected, select) {
  const wrap = el("nav", "w-64 shrink-0 overflow-y-auto border-r border-slate-200 px-4 py-4 dark:border-slate-800");
  wrap.id = "rail";
  wrap.append(el("h3", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", "Steps"));
  const ol = el("ol", "ml-1 border-l border-slate-200 dark:border-slate-700");
  list.forEach((a, i) => {
    const gap = a.step === VERIFY.id ? null : idle(list.slice(0, i).findLast((x) => x.step !== VERIFY.id), a); // a verification has no time of its own
    if (gap) ol.append(gap);
    if (a.after) ol.append(jump(a, list, i, select));
    ol.append(row(a, selected.step === a.step && selected.n === a.n, select));
  });
  const last = list.findLast((x) => x.step !== VERIFY.id);
  const reached = STEPS.findIndex((x) => x.id === last?.step);
  for (const s of STEPS.slice(reached + 1, -1)) {
    const li = el("li", "relative py-1.5 pl-4 text-[13px] text-slate-400 dark:text-slate-600");
    li.append(marker("border-slate-300 dark:border-slate-600"), `${s.emoji} ${s.label}`, el("span", "ml-2 text-[11px]", "pending"));
    ol.append(li);
  }
  ol.append(landRow(t, last));
  wrap.append(ol);
  return wrap;
}
