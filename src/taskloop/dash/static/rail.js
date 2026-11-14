// One row per step attempt, with the factory's verification attached to its agent answer.
// Past history is folded for display only; selection still uses the original (step, n).
import { JUMP, LAND, STATE, STEPS, VERIFY, dot, el, fmtDur, since, stepInfo } from "./ui.js";
import { say, wordNode } from "./words.js";
import { usageNode, usageText } from "./usage.js";

const WORK_MS = 120000;
const muted = "text-slate-500 dark:text-slate-400";
const chosen = (a, selected) => a && selected.step === a.step && selected.n === a.n;
const marker = (cls) => el("span", `absolute -left-[3px] top-[0.8rem] h-1.5 w-1.5 rounded-full border ${cls}`);

export function lasted(a) {
  if (a.step === VERIFY.id || !a.started_at) return "—";
  const end = a.ended_at ? Date.parse(a.ended_at) : a.state === "running" ? Date.now() : NaN;
  const ms = end - Date.parse(a.started_at);
  return Number.isFinite(ms) && ms >= 0 ? (a.ended_at ? fmtDur(ms) : since(a.started_at)) : "—";
}

export function verifyTitle(list, a) {
  const of = list[list.indexOf(a) - 1];
  return `Check of ${stepInfo(of?.step ?? a.step).label}${of?.n > 1 ? ` attempt ${of.n}` : ""}`;
}

// Explicitly normalize the old presentation placeholder; it is not a recorded cause.
export function changeReason(a) {
  if (!a.reason || (a.after === "restart_at_plan" && a.reason === "restarted at plan")) return "Reason not recorded";
  return say(a.reason);
}

function gapBetween(prev, next) {
  if (!prev?.ended_at || !next.started_at) return null;
  const ms = Date.parse(next.started_at) - Date.parse(prev.ended_at);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

function gapWords(ms) {
  return ms === null ? "" : `Approximate elapsed gap: ${fmtDur(ms)} between recorded step times; not a measurement of individual factory operations.`;
}

// The ordering contract puts verification immediately after its agent, with its own task-wide number.
function project(list) {
  const groups = [];
  let previous = null;
  for (const a of list) {
    if (a.step === VERIFY.id) {
      const entry = groups.at(-1)?.at(-1);
      if (entry && ["plan", "implement"].includes(entry.a.step) && !entry.verification) entry.verification = a;
      continue;
    }
    if (!groups.length || a.after === "restart_at_plan") groups.push([]);
    groups.at(-1).push({ a, verification: null, gap: gapBetween(previous, a) });
    previous = a;
  }
  return groups;
}

function verdict(a) {
  if (["verified", "reused"].includes(a.summary)) return { mark: "✓", label: say(a.summary), failed: false, text: STATE.succeeded.text };
  if (a.state === "running" && (!a.summary || ["pending", "registered"].includes(a.summary))) {
    return { mark: "…", label: "Not checked yet", failed: false, text: muted };
  }
  const missing = !a.summary || ["pending", "registered"].includes(a.summary);
  const why = missing ? "verification outcome was not recorded" : say(a.summary);
  const label = why.startsWith("Not committed:") ? why : `Not committed: ${why}`;
  return { mark: "✗", label, failed: true, text: STATE.failed.text };
}

function verificationButtons(a, selected, select, agent) {
  const v = verdict(a);
  const mark = el("button", `shrink-0 rounded px-2 py-1.5 text-sm ${v.text} ${chosen(a, selected) ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"}`, v.mark);
  mark.type = "button";
  const of = `${stepInfo(agent.step).label}${agent.n > 1 ? ` attempt ${agent.n}` : ""}`;
  mark.title = `${of}: ${v.label}${a.summary ? ` (${a.summary})` : ""}`;
  mark.setAttribute("aria-label", `Verification of ${of}: ${v.label}. Open Result`);
  mark.setAttribute("aria-pressed", String(!!chosen(a, selected)));
  if (chosen(a, selected)) mark.dataset.selected = "1";
  mark.addEventListener("click", () => select(a.step, a.n));
  if (!v.failed) return [mark, null];
  const reason = el("button", `block w-full truncate px-2 text-left text-[11px] ${v.text} hover:underline`, v.label);
  reason.type = "button";
  reason.title = mark.title;
  reason.addEventListener("click", () => select(a.step, a.n));
  return [mark, reason];
}

function restartTime(iso) {
  if (!iso) return "";
  const at = new Date(iso), today = new Date();
  if (!Number.isFinite(at.getTime())) return "";
  const sameDay = at.toDateString() === today.toDateString();
  const options = { hour12: false, hour: "2-digit", minute: "2-digit", ...(sameDay ? {} : { month: "short", day: "numeric" }) };
  return ` · ${at.toLocaleString([], options)}`;
}

function restart({ a, gap }, select) {
  const li = el("li", "relative pb-0.5 pl-4 pt-1.5");
  const btn = el("button", `block w-full text-left text-[11px] leading-snug hover:underline ${JUMP.restart_at_plan.text}`,
    `Restarted at plan${restartTime(a.started_at)}${gap === null ? "" : ` · waited ${fmtDur(gap)}`}`);
  btn.type = "button";
  btn.title = `${changeReason(a)}${gap === null ? "" : ` · ${gapWords(gap)}`}`;
  btn.addEventListener("click", () => select(a.step, a.n));
  li.append(btn);
  return li;
}

// Cause navigation remains in the selected attempt detail, never an extra rail row.
export function causeLink(a, select) {
  const btn = el("button", "block text-left text-[11px] underline decoration-dotted underline-offset-2 hover:decoration-solid", "because the factory's check of the answer failed →");
  btn.type = "button";
  btn.addEventListener("click", () => select(VERIFY.id, a.led_by));
  return btn;
}

function row({ a, verification, gap }, selected, select, stepUsage) {
  const st = STATE[a.state];
  const li = el("li", `relative pl-3 ${a.past ? "opacity-60" : ""}`);
  if (!a.after) li.title = gapWords(gap);
  const dotEl = dot(st.dot);
  dotEl.classList.add("absolute", "-left-[3px]", "top-[0.95rem]");
  const line = el("div", "flex items-center");
  const btn = el("button", `block min-w-0 flex-1 rounded px-2 py-1.5 text-left ${chosen(a, selected) ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"}`);
  btn.type = "button";
  if (chosen(a, selected)) btn.dataset.selected = "1";
  const top = el("span", "flex items-baseline gap-1");
  top.append(el("span", "text-[13px] font-medium", stepInfo(a.step).label));
  if (a.n > 1) top.append(el("span", `text-[11px] ${muted}`, `attempt ${a.n}`));
  if (a.after === "repeat") {
    const tag = el("span", `text-[11px] ${JUMP.repeat.text}`, "Repeat");
    tag.title = `Repeat of ${stepInfo(a.step).label}${a.repeat_of ? ` attempt ${a.repeat_of}` : ""}: ${changeReason(a)}`
      + (a.reason ? ` (${a.reason})` : "") + (gap === null ? "" : ` · ${gapWords(gap)}`);
    top.append(tag);
  }
  top.append(el("span", `ml-auto text-[11px] tabular-nums ${muted}`, lasted(a)));
  btn.append(top);
  const covered = verification && (a.summary === "verification" || a.summary === verification.summary);
  if (a.state === "failed" && !covered) btn.append(wordNode(el, a.summary, `mt-0.5 block truncate text-[11px] ${muted}`));
  btn.addEventListener("click", () => select(a.step, a.n));
  line.append(btn);
  li.append(dotEl, line);
  if (a.usage) {
    li.title = [li.title, usageText(a.usage), usageText(stepUsage, "Step total", true)].filter(Boolean).join(" · ");
    const total = el("div", "px-2 pb-1");
    total.append(usageNode(stepUsage, "Step total", true));
    li.append(total);
  }
  if (verification) {
    const [mark, reason] = verificationButtons(verification, selected, select, a);
    line.append(mark);
    if (reason) li.append(reason);
  }
  return li;
}

function summary(entries, n) {
  const parts = [`History ${n}`];
  for (const step of STEPS.slice(0, -1)) {
    const tries = entries.filter(({ a }) => a.step === step.id);
    if (!tries.length) continue;
    const last = tries.at(-1);
    const status = ({ a, verification }) => verification ? verdict(verification).mark : a.state === "failed" ? "✗" : step.id === "checks" && a.state === "succeeded" ? "✓" : "…";
    const earlierFailure = tries.slice(0, -1).some((entry) => status(entry) === "✗");
    parts.push(`${step.label} ${status(last)}${earlierFailure ? " (earlier failure)" : ""}`);
  }
  return parts.join(" · ");
}

function groupRows(entries, selected, select, stepUsage) {
  const ol = el("ol", "ml-1 border-l border-slate-200 dark:border-slate-700");
  for (const entry of entries) {
    if (entry.a.after === "restart_at_plan") ol.append(restart(entry, select));
    if (!entry.a.after && entry.gap !== null && entry.gap >= WORK_MS) {
      const work = el("li", "relative py-1 pl-4 text-[11px] text-slate-400 dark:text-slate-500", `Factory work · ${fmtDur(entry.gap)}`);
      work.title = gapWords(entry.gap);
      ol.append(work);
    }
    ol.append(row(entry, selected, select, stepUsage[entry.a.step]));
  }
  return ol;
}

function pastGroup(entries, n, selected, select, stepUsage) {
  const key = `${entries[0].a.step}/${entries[0].a.n}`;
  const details = el("details", "mb-2");
  details.dataset.run = key;
  const selectedKey = `${selected.step}/${selected.n}`;
  const containsSelection = entries.some(({ a, verification }) => chosen(a, selected) || chosen(verification, selected));
  // A newly selected result opens its group; redraws preserve the person's disclosure choice.
  if (containsSelection && selected.railSelection !== selectedKey) selected.runs.set(key, true);
  details.open = selected.runs.get(key) ?? false;
  const heading = el("summary", `cursor-pointer text-[11px] ${muted}`, summary(entries, n));
  heading.title = "Expand to inspect every attempt and verification result, including earlier failures";
  details.append(heading, groupRows(entries, selected, select, stepUsage));
  details.addEventListener("toggle", () => { if (details.isConnected) selected.runs.set(key, details.open); });
  return details;
}

function landRow(t) {
  const here = t.column === "land" || t.column === "landed";
  const word = t.column === "landed" ? LAND.done : here ? LAND[t.land ?? "unknown"] : null;
  const li = el("li", `relative py-1.5 pl-4 ${here ? "" : "text-slate-400 dark:text-slate-600"}`);
  li.append(marker(t.column === "landed" ? "border-emerald-500 bg-emerald-500" : here ? "border-amber-500" : "border-slate-300 dark:border-slate-600"), el("span", `text-[13px] ${here ? "font-medium" : ""}`, `${STEPS.at(-1).emoji} ${STEPS.at(-1).label}`));
  if (word) li.append(el("span", `block text-[11px] ${word.text}`, t.status_note ?? word.row));
  else li.append(el("span", "ml-2 text-[11px]", "pending"));
  return li;
}

export function rail(list, t, selected, select, stepUsage = {}) {
  selected.runs ??= new Map();
  const wrap = el("nav", "w-64 shrink-0 overflow-y-auto border-r border-slate-200 px-4 py-4 dark:border-slate-800");
  wrap.id = "rail";
  wrap.append(el("h3", "mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500", "Steps"));
  const groups = project(list);
  let current = null;
  groups.forEach((entries, i) => {
    if (entries.every(({ a }) => a.past)) wrap.append(pastGroup(entries, i + 1, selected, select, stepUsage));
    else { current = groupRows(entries, selected, select, stepUsage); wrap.append(current); }
  });
  selected.railSelection = `${selected.step}/${selected.n}`;
  if (t.column === "waiting") return wrap;
  if (!current) { current = el("ol", "ml-1 border-l border-slate-200 dark:border-slate-700"); wrap.append(current); }
  const last = list.findLast((a) => a.step !== VERIFY.id && !a.past);
  const reached = STEPS.findIndex((s) => s.id === last?.step);
  for (const s of STEPS.slice(reached + 1, -1)) {
    const li = el("li", "relative py-1.5 pl-4 text-[13px] text-slate-400 dark:text-slate-600");
    li.append(marker("border-slate-300 dark:border-slate-600"), `${s.emoji} ${s.label}`, el("span", "ml-2 text-[11px]", "pending"));
    current.append(li);
  }
  current.append(landRow(t));
  return wrap;
}
