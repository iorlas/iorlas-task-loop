// One selected detail panel, with recorded event facts above the existing output.
import { COMMIT, JUMP, STATE, ago, el, elapsedSpan, quietSpan, stepInfo, tag } from "./ui.js";
import { causeLink, causeWords, changeReason, commitTitle, lasted } from "./rail.js";
import { usageNode } from "./usage.js";

const words = (value) => String(value).replaceAll("_", " ");
const labels = { rc: "Exit code", timed_out: "Timed out", held_at: "Hold recorded at", cause_id: "Deciding attempt",
  attempt_id: "Held attempt", source: "Source ref", target: "Target ref", checks: "Failed checks", check: "Deciding check",
  retry_cause: "Retry cause", admitted_at: "Admitted at", validated_at: "Validation finished at",
  released_at: "Release finished at", delivered_at: "Delivery finished at", closed_at: "Task completion confirmed at" };

function facts(value) {
  const list = el("dl", "space-y-1 text-xs");
  for (const [key, item] of Object.entries(value)) {
    if (item == null || (Array.isArray(item) && !item.length)) continue;
    const row = el("div", "pl-2");
    row.append(el("dt", "font-medium", labels[key] ?? words(key)), el("dd", "whitespace-pre-wrap break-words"));
    const target = row.lastChild;
    if (Array.isArray(item)) {
      const items = el("ul", "list-disc pl-4");
      for (const entry of item) {
        const li = el("li");
        li.append(typeof entry === "object" ? facts(entry) : document.createTextNode(String(entry)));
        items.append(li);
      }
      target.append(items);
    } else if (typeof item === "object") target.append(facts(item));
    else target.textContent = typeof item === "boolean" ? (item ? "Yes" : "No") : String(item);
    list.append(row);
  }
  return list;
}

export function detailPanel(title, badge = null) {
  const wrap = el("section", "attempt-pane flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto");
  const top = el("div", "flex flex-wrap items-center gap-x-3 gap-y-1 px-6 pt-4");
  top.append(el("h3", "text-sm font-semibold", title));
  if (badge) top.append(badge);
  wrap.append(top);
  return wrap;
}

function began(a, list, select) {
  const prev = a.after === "repeat" ? list.find((x) => x.step === a.step && x.n === a.repeat_of)
    : list.slice(0, list.indexOf(a)).findLast((x) => x.step !== COMMIT.id);
  const at = `${stepInfo(prev?.step ?? a.step).label}${prev ? `, attempt ${prev.n}` : ""}`;
  const what = a.after === "repeat" ? `a repeat of ${at}` : `a restart at plan (after ${at})`;
  const description = a.after === "repeat" && a.step === "checks" ? `Re-run after restart of ${at}` : `Began after ${what}`;
  const line = el("p", `w-full text-xs ${JUMP[a.after].text}`);
  line.append(el("span", "font-medium", description),
    el("span", "text-slate-500 dark:text-slate-400", ` · ${changeReason(a)}`));
  line.title = `${changeReason(a)}${a.reason ? ` (${a.reason})` : ""}`;
  if (a.led_by) line.append(" ", causeLink(a, select));
  return line;
}

export function attemptPanel(a, list, select) {
  const st = STATE[a.state];
  const title = a.step === COMMIT.id ? `${COMMIT.emoji} ${commitTitle(list, a)}`
    : `${stepInfo(a.step).emoji} ${stepInfo(a.step).label}, attempt ${a.n}`;
  const wrap = detailPanel(title, tag(st.label, { dotCls: st.dot, cls: st.text }));
  const top = wrap.firstChild;
  const timing = a.state === "running" ? "still running" : a.ended_at && a.started_at ? `ran ${lasted(a)}` : "end not recorded";
  if (["plan", "implement"].includes(a.step)) {
    const live = a.state === "running" && !a.duration?.frozen;
    top.append(elapsedSpan(a.duration, "text-xs text-slate-500 dark:text-slate-400", live ? "" : "ran ",
      live ? " in step, still running" : ""));
  } else if (a.step !== COMMIT.id) {
    top.append(el("span", "text-xs text-slate-500 dark:text-slate-400",
      `${a.started_at ? `started ${ago(a.started_at)}, ` : ""}${timing}`));
  }
  if (a.usage) top.append(usageNode(a.usage));
  if (a.state === "running" && ["plan", "implement"].includes(a.step) && !a.duration?.frozen) {
    const quiet = quietSpan(a.duration);
    quiet.id = "quiet";
    top.append(quiet);
  }
  if (a.run) wrap.append(el("p", "px-6 pt-1 text-xs text-slate-500 dark:text-slate-400",
    [a.run.harness, a.run.provider, a.run.model, `${a.run.effort} effort`, a.run.access].join(" · ")));
  if (a.after) top.append(began(a, list, select));
  if (a.context) {
    const context = el("div", "px-6 py-3");
    context.dataset.eventContext = a.context.event.cause_id;
    context.append(el("h4", "text-sm font-medium", "Recorded hold"), el("p", "whitespace-pre-wrap text-sm", causeWords(a.context)),
      facts({ held_at: a.context.held_at, ...a.context.event }));
    wrap.append(context);
  } else if (a.state === "failed" && a.step !== COMMIT.id) {
    wrap.append(el("p", "px-6 py-3 text-sm", "Reason not recorded"));
  }
  return wrap;
}

export function landPanel(event) {
  const title = event ? { ready: "Land ready", tried: "Land tried", landed: "Landed" }[event.kind] : "Land";
  const wrap = detailPanel(`${title}${event?.candidate_n == null ? "" : ` · candidate ${event.candidate_n}`} · Delivery details`);
  wrap.classList.add("overflow-y-auto");
  if (event) {
    const context = el("div", "px-6 py-3");
    context.dataset.eventContext = event.id;
    const { id, kind, waits, past, ...recorded } = event;
    context.append(el("h4", "text-sm font-medium", `${past ? "Historical · " : ""}Recorded event`), facts(recorded));
    for (const wait of waits) context.append(facts(wait));
    wrap.append(context);
  }
  wrap.append(el("h4", "px-6 pt-4 text-sm font-semibold", "Current delivery"));
  return wrap;
}
