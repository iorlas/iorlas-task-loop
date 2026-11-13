// The Lines tab of one attempt: the agent's latest actions as a grid, kept where the person scrolled it.
// Shapes: docs/design/dashboard-ui.md (*Live event*).

import { $, FEED_LIMIT, clock, el, fmtDur, tick } from "./ui.js";

const KIND = { command: "💻", tool: "🧰", message: "💬", error: "❌", waiting: "⏳", check: "🧪", step: "🚦" };
const WORD = { command: "Command", tool: "Tool", message: "Agent message", error: "Error", waiting: "Waiting", check: "Check", step: "Step" };
const PAUSE_MS = 2000; // a pause shorter than this is not worth a row
const BOTTOM_PX = 24; // within this of the end counts as "at the bottom"

// The idle time before a line: the producer's measure (`waited_ms`), else the time since the previous line ended.
export function pause(e, prev) {
  if (e.type === "step" || !prev) return 0;
  if (e.waited_ms != null) return e.waited_ms;
  return Date.parse(e.at) - Date.parse(prev.at) - (prev.duration_ms ?? 0);
}

export const atBottom = (box) => box.scrollHeight - box.scrollTop - box.clientHeight < BOTTOM_PX;

export function lines(a) {
  const box = el("div", "min-h-0 flex-1 overflow-y-auto px-6 py-4");
  box.id = "tail";
  box.dataset.key = `${a.step}/${a.n}`;
  const list = el("div", "divide-y divide-slate-100 dark:divide-slate-800/70");
  list.id = "lines";
  if (!a.feed.length) list.append(el("p", "py-3 text-sm text-slate-500", "No lines recorded for this attempt."));
  a.feed.forEach((e, i) => list.append(line(e, a, a.feed[i - 1])));
  box.append(el("p", "mb-1 text-[11px] text-slate-400 dark:text-slate-500", `Latest ${FEED_LIMIT} lines${a.state === "running" ? ", live" : ""}`), list);
  return box;
}

// One row: offset, kind emoji, content, duration. A faint "paused 33s" row sits above a line that came after a pause.
function line(e, a, prev) {
  const idle = pause(e, prev);
  const row = el("div", "animate-line-in grid grid-cols-[3.25rem_3.25rem_minmax(0,1fr)_auto] items-baseline gap-x-3 py-1.5 text-xs");
  row.dataset.eid = e.id || "";
  const hint = idle >= PAUSE_MS;
  const r = hint ? "row-start-2" : "row-start-1"; // literal class names: the Tailwind scanner reads strings, not parts
  if (hint) row.append(el("span", "col-start-3 row-start-1 mb-0.5 text-[11px] text-slate-400 dark:text-slate-500", `⏸ paused ${fmtDur(idle)}`));
  const at = el("span", `col-start-1 ${r} font-mono tabular-nums text-slate-400 dark:text-slate-500`, clock(Date.parse(e.at) - Date.parse(a.started_at)));
  const kind = el("span", `col-start-2 ${r} text-[13px]`, KIND[e.type]);
  kind.title = WORD[e.type];
  const content = el("span", `col-start-3 ${r} min-w-0`);
  const right = el("span", `col-start-4 ${r} text-right tabular-nums text-slate-500 dark:text-slate-400`);
  fill(e, content, right);
  row.append(at, kind, content, right);
  return row;
}

function fill(e, content, right) {
  if (e.type === "command" || e.type === "tool") {
    const running = e.state === "running";
    const failed = !running && e.exit_code != null && e.exit_code !== 0;
    if (e.type === "tool") content.append(el("span", "font-semibold text-slate-600 dark:text-slate-300", e.name), " ");
    content.append(el("code", `${e.type === "tool" ? "" : "block "}truncate font-mono text-[12px]`, e.cmd));
    if (running) {
      right.dataset.since = e.at;
      right.dataset.prefix = "running ";
      right.className += " text-sky-600 dark:text-sky-400";
      tick(right);
    } else {
      right.textContent = e.state === "unfinished" ? "unfinished" : `${e.duration_ms == null ? "" : fmtDur(e.duration_ms)}${failed ? `  exit ${e.exit_code}` : ""}`;
      if (failed) right.className += " font-medium text-rose-600 dark:text-rose-400";
    }
  } else if (e.type === "message") {
    content.className += " whitespace-pre-wrap break-words text-slate-700 dark:text-slate-200"; // what the agent said, in full
    content.textContent = e.text;
  } else if (e.type === "error" || e.type === "waiting") {
    content.className += e.type === "error" ? " font-medium text-rose-600 dark:text-rose-400" : " text-amber-600 dark:text-amber-400";
    content.textContent = e.text;
  } else if (e.type === "check") {
    content.append(el("span", "font-mono text-[12px]", e.name), "  ", el("span", `font-medium ${e.passed ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`, e.passed ? "passed" : "failed"));
    right.textContent = fmtDur(e.duration_ms);
  } else {
    content.append(el("span", "text-slate-500 dark:text-slate-400", `try ${e.attempt} of ${e.step} started`));
  }
}

// One new line of an attempt: a command's finished line replaces its running one (same id); the feed keeps its last FEED_LIMIT.
export function apply(attempt, e) {
  const at = e.id ? attempt.feed.findIndex((x) => x.id === e.id) : -1;
  if (at >= 0) attempt.feed[at] = e;
  else attempt.feed.push(e);
  attempt.feed = attempt.feed.slice(-FEED_LIMIT);
}

// The new line in the open Lines tab: in place of its running line, else at the end. The view follows the end only when it was
// already there; a person who scrolled up keeps the place, even while the oldest rows drop off the top.
export function show(attempt, e) {
  const list = $("lines");
  const box = $("tail");
  if (!list || !box || box.dataset.key !== `${attempt.step}/${attempt.n}`) return;
  const follow = atBottom(box);
  if (list.firstChild?.tagName === "P") list.replaceChildren();
  const index = attempt.feed.indexOf(e);
  const row = line(e, attempt, attempt.feed[index - 1]);
  const old = e.id && [...list.children].find((c) => c.dataset.eid === e.id);
  if (old) old.replaceWith(row);
  else list.append(row);
  const height = box.scrollHeight;
  let dropped = false;
  while (list.children.length > FEED_LIMIT) {
    list.firstChild.remove();
    dropped = true;
  }
  if (follow) box.scrollTop = box.scrollHeight;
  else if (dropped) box.scrollTop -= height - box.scrollHeight;
}
