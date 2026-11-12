// The Logs screen: the factory's one round log (`rounds.log`), newest first. Display only; the backend's reader
// turns each line into the typed row below (docs/design/dashboard-ui.md).

import { $, el } from "./ui.js";

const MOVE = {
  hold: "text-rose-600 dark:text-rose-400",
  skip: "text-amber-600 dark:text-amber-400",
  repeat: "text-amber-600 dark:text-amber-400",
  publish: "text-emerald-600 dark:text-emerald-400",
};
const ATTENTION_WORDS = ["failed", "no_free_slot", "restart_at_plan", "paused"];
const attention = (r) => ["hold", "skip", "repeat"].includes(r.move) || r.words.some((w) => ATTENTION_WORDS.includes(w) || w.startsWith("unusable"));

let rows = []; // oldest first, as the reader returns them
let filter = "all";
let openTask = null;

export function initLogs(openTaskFn) {
  openTask = openTaskFn;
}

export async function loadLogs(source) {
  rows = (await source.logs()).rows;
  render();
}

export function onLog(row) {
  rows.push(row);
  if (!$("logs").hidden) render(row);
}

const dayLabel = (d) => {
  const today = new Date().toDateString();
  if (d.toDateString() === today) return "Today";
  if (new Date(Date.now() - 864e5).toDateString() === d.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
};

function render(fresh) {
  const box = $("logs");
  const shown = rows.filter((r) => filter === "all" || attention(r)).slice().reverse();
  box.replaceChildren();
  const bar = el("div", "flex items-center gap-3 px-1 pb-3");
  bar.append(el("h2", "text-sm font-semibold", "Factory log"), el("span", "text-xs text-slate-500 dark:text-slate-400", `rounds.log · one line per move · ${shown.length} of ${rows.length} lines`));
  const live = el("span", "inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400");
  live.append(el("span", "h-1.5 w-1.5 animate-pulse-dot rounded-full bg-sky-500"), "Live");
  const seg = el("div", "ml-auto flex gap-0.5 rounded-md bg-slate-200/70 p-0.5 dark:bg-slate-800");
  for (const [id, label] of [["all", "All moves"], ["attention", "Needs attention"]]) {
    const b = el("button", `rounded px-2.5 py-1 text-xs font-medium ${filter === id ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"}`, label);
    b.type = "button";
    b.addEventListener("click", () => { filter = id; render(); });
    seg.append(b);
  }
  bar.append(live, seg);
  const table = el("div", "min-h-0 flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-white px-4 dark:border-slate-800 dark:bg-slate-900");
  let day = "";
  for (const r of shown) {
    const at = new Date(r.at);
    const label = dayLabel(at);
    if (label !== day) {
      day = label;
      table.append(el("div", "sticky top-0 z-10 -mx-4 border-b border-slate-100 bg-slate-50 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:border-slate-800 dark:bg-slate-900/95", label));
    }
    const row = el("div", `grid grid-cols-[4.5rem_4.5rem_4rem_minmax(0,1fr)] items-baseline gap-x-3 border-b border-slate-100 py-1.5 text-xs last:border-0 dark:border-slate-800/70 ${r === fresh ? "animate-line-in" : ""}`);
    row.append(el("span", "font-mono tabular-nums text-slate-400 dark:text-slate-500", at.toLocaleTimeString([], { hour12: false })));
    if (r.task) {
      const link = el("button", "text-left font-mono text-slate-700 hover:underline dark:text-slate-200", r.task);
      link.type = "button";
      link.addEventListener("click", () => openTask(r.task));
      row.append(link);
    } else row.append(el("span", "text-slate-400", "factory"));
    row.append(el("span", `text-[10px] font-semibold uppercase tracking-wider ${MOVE[r.move] ?? "text-slate-500 dark:text-slate-400"}`, r.move), el("span", "min-w-0 truncate font-mono text-[12px] text-slate-600 dark:text-slate-300", r.words.join("  ")));
    table.append(row);
  }
  if (!shown.length) table.append(el("p", "py-6 text-sm text-slate-500", "Nothing needs attention."));
  box.append(bar, table);
}
