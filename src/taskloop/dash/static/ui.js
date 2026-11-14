// Shared constants and small DOM helpers for the dashboard page.

import { say } from "./words.js";

export const COLUMNS = [
  { id: "waiting", label: "Ready", emoji: "⏳", help: "Approved by the person and not yet admitted to a slot." },
  { id: "plan", label: "Plan", emoji: "🧭", help: "A plan attempt is running in a slot." },
  { id: "implement", label: "Implement", emoji: "🛠️", help: "An implement attempt is running in a slot." },
  { id: "checks", label: "Checks", emoji: "🧪", help: "A checks attempt is running the profile's checks." },
  { id: "land", label: "Land", emoji: "🚀", help: "Checked and ready to land. A round lands it by itself when the repository profile says land: auto; under manual it waits for a person. A card says landing only while a land runs." },
  { id: "held", label: "Held", emoji: "⛔", help: "The factory will not advance this task until a person acts. The hold cause says what to do." },
  { id: "landed", label: "Landed", emoji: "✅", help: "Landed on main and closed." },
];
export const STEPS = COLUMNS.slice(1, 5);
// The factory's verification is a mark on its agent attempt's rail row; it has its own Result, but no column.
export const VERIFY = { id: "verification", label: "Verification", emoji: "🔎" };
export const stepInfo = (id) => (id === VERIFY.id ? VERIFY : STEPS.find((s) => s.id === id));
export const STATE = {
  running: { label: "Running", dot: "bg-sky-500 animate-pulse-dot", text: "text-sky-700 dark:text-sky-300" },
  succeeded: { label: "Succeeded", dot: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300" },
  failed: { label: "Failed", dot: "bg-rose-500", text: "text-rose-700 dark:text-rose-300" },
};
export const JUMP = {
  repeat: { label: "Repeat", glyph: "↻", text: "text-amber-700 dark:text-amber-300", bar: "border-amber-500" },
  restart_at_plan: { label: "Restarted at plan", glyph: "↩", text: "text-violet-700 dark:text-violet-300", bar: "border-violet-500" },
};
// The Land column's states (`card.land`): what the card says, and what the drawer's rail row says.
export const LAND = {
  waiting: { label: "Waiting for the factory", text: "text-amber-700 dark:text-amber-300", bar: "border-amber-500" },
  unknown: { label: "Landing policy unavailable", text: "text-amber-700 dark:text-amber-300", bar: "border-amber-500" },
  manual: { label: "Waiting for a person", row: "waiting for a person: the profile says land: manual", text: "text-amber-700 dark:text-amber-300", bar: "border-amber-500" },
  landing: { label: "Landing", row: "landing on main now", text: "text-sky-700 dark:text-sky-300", bar: "border-sky-500" },
  done: { row: "landed on main", text: "text-emerald-700 dark:text-emerald-300" },
};
export const FEED_LIMIT = 20;

export const $ = (id) => document.getElementById(id);
export const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
export const dot = (cls) => el("span", `inline-block h-1.5 w-1.5 shrink-0 rounded-full ${cls}`);

// A small outlined label with an optional leading dot: the one badge shape of the page.
export function tag(text, { dotCls, cls = "text-slate-600 dark:text-slate-300" } = {}) {
  const node = el("span", `inline-flex items-center gap-1.5 rounded border border-slate-200 px-1.5 text-[11px] font-medium leading-5 dark:border-slate-700 ${cls}`);
  if (dotCls) node.append(dot(dotCls));
  node.append(text);
  return node;
}

// A callout: one accent line, no fill. Used for repeat reasons, hold causes and failures alike.
const BAR_TEXT = {
  "border-rose-500": "text-rose-700 dark:text-rose-300", "border-amber-500": "text-amber-700 dark:text-amber-300",
  "border-violet-500": "text-violet-700 dark:text-violet-300", "border-sky-500": "text-sky-700 dark:text-sky-300",
  "border-emerald-500": "text-emerald-700 dark:text-emerald-300",
};
export function callout(barCls, head, body) {
  const node = el("div", `border-l-2 pl-2.5 text-xs leading-snug ${barCls}`);
  if (head) node.append(el("p", `font-medium ${BAR_TEXT[barCls] ?? ""}`, head));
  if (body) {
    const text = el("p", "mt-0.5 text-slate-600 dark:text-slate-300", say(body)); // a typed code shows its words, the code as hover text
    if (say(body) !== body) text.title = body;
    node.append(text);
  }
  return node;
}

export function fmtDur(ms) {
  if (ms < 1000) return `${Math.max(Math.round(ms), 0)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(Math.floor(s % 60)).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
// Where a task is, in words that keep a step apart from a try: "step 2 of 4 · try 1" (the land has no tries of its own).
export function position(t) {
  const at = STEPS.findIndex((s) => s.id === t.column);
  if (at < 0) return null;
  return `step ${at + 1} of ${STEPS.length}${t.column === "land" ? "" : ` · try ${t.attempt}`}`;
}
export const since = (iso) => fmtDur(Date.now() - Date.parse(iso));
export const ago = (iso) => `${since(iso)} ago`;
// When a restart began: the time of day and how long ago (an attempt the stores gave no start shows neither).
export const startedAt = (iso) => (iso ? ` ${new Date(iso).toLocaleString([], { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}, ${ago(iso)}` : "");
export const clock = (ms) => `+${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

// Quiet time of running work: nothing under 2 minutes, then amber, red from 15 minutes. Display only.
const QUIET_AFTER_S = 120;
const QUIET_LONG_S = 900;
function tickQuiet(node) {
  const s = (Date.now() - Date.parse(node.dataset.quiet)) / 1000;
  const level = s >= QUIET_LONG_S ? "long" : s >= QUIET_AFTER_S ? "slow" : "";
  node.hidden = !level;
  node.replaceChildren(dot(level === "long" ? "bg-rose-500" : "bg-amber-500"), `Quiet ${fmtDur(s * 1000)}`);
  node.className = `${node.closest("article") ? "mt-2 w-fit" : ""} inline-flex items-center gap-1.5 text-[11px] font-medium ${level === "long" ? "text-rose-700 dark:text-rose-300" : "text-amber-700 dark:text-amber-300"}`;
  const card = node.closest("article");
  if (card) card.dataset.quietLevel = level;
}
export function tick(node) {
  if (node.dataset.quiet) return tickQuiet(node);
  node.textContent = `${node.dataset.prefix || ""}${since(node.dataset.since)}${node.dataset.suffix || ""}`;
}
export function quietSpan(sinceIso) {
  const node = el("span");
  node.dataset.quiet = sinceIso;
  tick(node);
  return node;
}
