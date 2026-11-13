// The step rail of the drawer: the task's steps top to bottom in the order they happened (plan, implement, checks, land), each with
// its own try number, the idle time between two steps, and a repeat named as a repeat with its reason. A step and a try are two
// things: "step 2 of 4" is where the task is, "try 2" is how often that step ran.

import { JUMP, LAND, STATE, STEPS, dot, el, fmtDur, since } from "./ui.js";

const GAP_MS = 5000; // idle time shorter than this is not shown
const stepOf = (id) => STEPS.find((s) => s.id === id);

// How long an attempt ran, or has been running; an attempt the stores gave no start or end shows a dash.
export function lasted(a) {
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
  li.title = "Nothing ran between the end of the step above and the start of this one.";
  return li;
}

function jump(a, prev) {
  const j = JUMP[a.after];
  const li = el("li", `relative pb-0.5 pl-4 pt-1.5 text-[11px] leading-snug ${j.text}`);
  li.title = a.reason ?? "";
  li.append(el("span", "font-medium", `${j.glyph} ${j.label} of ${stepOf(prev?.step ?? a.step).label}`));
  if (a.reason) li.append(el("span", "block line-clamp-2 text-slate-500 dark:text-slate-400", a.reason));
  return li;
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
  if (a.state === "failed") btn.append(el("span", "mt-0.5 block truncate text-[11px] text-slate-500 dark:text-slate-400", a.summary));
  btn.addEventListener("click", () => select(a.step, a.n));
  li.append(dotEl, btn);
  return li;
}

// The land is not an attempt of its own in the history yet: its row is the card's state (waiting for the person, delivering, done).
function landRow(t) {
  const word = t.column === "landed" ? LAND.done : LAND[t.land ?? "waiting"];
  const li = el("li", "relative py-1.5 pl-4");
  li.append(marker(t.column === "landed" ? "border-emerald-500 bg-emerald-500" : "border-amber-500"), el("span", "text-[13px] font-medium", `${STEPS.at(-1).emoji} ${STEPS.at(-1).label}`));
  li.append(el("span", `block text-[11px] ${word.text}`, word.row));
  if (t.column === "land" && t.land !== "delivering") li.append(el("code", "block truncate font-mono text-[11px] text-slate-500 dark:text-slate-400", `tl step land ${t.id}`));
  return li;
}

export function rail(list, t, selected, select) {
  const wrap = el("nav", "w-64 shrink-0 overflow-y-auto border-r border-slate-200 px-4 py-4 dark:border-slate-800");
  wrap.append(el("h3", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", "Steps"));
  const ol = el("ol", "ml-1 border-l border-slate-200 dark:border-slate-700");
  list.forEach((a, i) => {
    const gap = idle(list[i - 1], a);
    if (gap) ol.append(gap);
    if (a.after) ol.append(jump(a, list[i - 1]));
    ol.append(row(a, selected.step === a.step && selected.n === a.n, select));
  });
  const last = list.at(-1);
  if (STEPS.some((s) => s.id === t.column) && t.column !== "land" && last?.state !== "failed") {
    for (const s of STEPS.slice(STEPS.findIndex((x) => x.id === last.step) + 1)) {
      const li = el("li", "relative py-1.5 pl-4 text-[13px] text-slate-400 dark:text-slate-600");
      li.append(marker("border-slate-300 dark:border-slate-600"), `${s.emoji} ${s.label}`);
      ol.append(li);
    }
  } else if (t.column === "land" || t.column === "landed") ol.append(landRow(t));
  wrap.append(ol);
  return wrap;
}
