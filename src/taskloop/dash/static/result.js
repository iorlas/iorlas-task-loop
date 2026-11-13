// The Result and Prompt tabs of one attempt: the conclusion, the agent's answer (formatted, with a raw toggle) and each check's
// output (a failed one open, a passed one folded). Display only.

import { STATE, callout, el, fmtDur, tag } from "./ui.js";

const BLOCK = "min-h-0 flex-1 overflow-y-auto px-6 py-4";
const pre = (text, cls = "") => el("pre", `max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-3 font-mono text-[11.5px] leading-relaxed dark:border-slate-800 dark:bg-slate-950/60 ${cls}`, text);
const label = (text) => el("h4", "mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500", text);
const words = (key) => key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());

// The answer file is the agent's JSON object. Its fields are shown as labelled text; anything that is not an object, or does not
// parse, is shown as it is. Nothing is decided from it.
function fieldsOf(text) {
  try {
    const found = JSON.parse(text);
    return found && typeof found === "object" && !Array.isArray(found) ? Object.entries(found) : null;
  } catch {
    return null;
  }
}

function answer(a) {
  const wrap = el("div");
  const head = el("div", "mb-1.5 flex items-center gap-3");
  head.append(label("Agent answer"), tag(a.disposition));
  const fields = fieldsOf(a.text);
  let raw = !fields;
  const toggle = el("button", "ml-auto rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800", "Raw");
  toggle.type = "button";
  const body = el("div");
  const paint = () => {
    toggle.textContent = raw ? "Formatted" : "Raw";
    toggle.hidden = !fields;
    body.replaceChildren(...(raw ? [pre(a.text, "max-h-96")] : fields.map(([key, value]) => {
      const row = el("div", "border-t border-slate-100 py-2 first:border-t-0 dark:border-slate-800/70");
      const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      row.append(el("dt", "mb-0.5 text-[11px] font-semibold text-slate-500 dark:text-slate-400", words(key)), el("dd", `whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-700 dark:text-slate-200 ${typeof value === "string" ? "" : "font-mono text-[12px]"}`, text));
      return row;
    })));
  };
  toggle.addEventListener("click", () => { raw = !raw; paint(); });
  head.append(toggle);
  paint();
  wrap.append(head, body);
  return wrap;
}

// One check: a failed one opens with its output, a passed one is folded; a log that is gone says so.
function check(c, blocks) {
  const node = el("details", "border-t border-slate-100 py-2 first:border-t-0 dark:border-slate-800/70");
  node.open = !c.passed;
  const top = el("summary", "flex cursor-pointer items-baseline gap-3 text-xs");
  top.append(el("span", "font-mono text-[12px]", c.name), el("span", `font-medium ${c.passed ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`, c.passed ? "passed" : "failed"));
  if (blocks > 1) top.append(el("span", "text-slate-500", `block ${c.block}`));
  top.append(el("span", "ml-auto tabular-nums text-slate-500", fmtDur(c.duration_ms)));
  node.append(top, c.output == null ? el("p", "mt-2 text-xs text-slate-500", "Output unavailable: the log file is gone or cannot be read.") : pre(c.output || "(no output)", `mt-2 ${c.passed ? "" : "border-l-2 border-l-rose-500"}`));
  return node;
}

export function result(a) {
  const box = el("div", `${BLOCK} flex flex-col gap-5`);
  const st = STATE[a.state];
  const summary = el("div");
  summary.append(label("Conclusion"), callout(a.state === "failed" ? "border-rose-500" : a.state === "running" ? "border-sky-500" : "border-emerald-500", null, a.result.summary));
  box.append(summary);
  if (a.result.answer) box.append(answer(a.result.answer));
  if (a.result.checks.length) {
    const wrap = el("div");
    wrap.append(label(`Checks · ${a.result.checks.length} · the end of each log, failed ones first`));
    const blocks = new Set(a.result.checks.map((c) => c.block)).size;
    const sorted = [...a.result.checks].sort((x, y) => x.passed - y.passed);
    for (const c of sorted) wrap.append(check(c, blocks));
    box.append(wrap);
  } else if (a.result.output) {
    const out = el("div");
    out.append(label("Output"), pre(a.result.output, "border-l-2 border-l-rose-500"));
    box.append(out);
  }
  if (a.state === "running") box.append(el("p", "text-xs text-slate-500", `${st.label}: the result is written when the attempt ends.`));
  return box;
}

export function prompt(a) {
  const box = el("div", BLOCK);
  if (!a.input) {
    box.append(el("p", "text-sm text-slate-500", "No prompt: this step runs commands, not the agent."));
    return box;
  }
  box.append(label(`Input sent to the agent · ${a.input.length} characters`), pre(a.input, "max-h-none"));
  return box;
}
