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

// Terminal colour codes in a log are display noise here: stripped, the text is otherwise as written.
const ESCAPES = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
const plain = (text) => text.replace(ESCAPES, "");

function answer(a) {
  const wrap = el("div");
  const head = el("div", "mb-1.5 flex items-center gap-3");
  head.append(label("Agent answer"), tag(a.disposition));
  const fields = fieldsOf(a.text);
  let raw = !fields;
  const toggle = el("button", "ml-auto rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800", "Raw");
  toggle.type = "button";
  const body = el("dl");
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
  if (a.truncated) wrap.append(el("p", "mt-1 text-[11px] text-amber-700 dark:text-amber-300", "The answer file is longer than this: the end is cut (64 KiB shown). It is shown as it is."));
  return wrap;
}

// One check: a failed one opens with its output, a passed one is folded; a log that is gone says so.
function check(c, blocks, shown) {
  const node = el("details", "border-t border-slate-100 py-2 first:border-t-0 dark:border-slate-800/70");
  const key = `${shown.key}/${c.block}/${c.name}`;
  node.open = shown.opened.get(key) ?? !c.passed; // what the owner opened or closed stays, across the drawer's rebuilds
  node.addEventListener("toggle", () => shown.opened.set(key, node.open));
  const top = el("summary", "flex cursor-pointer items-baseline gap-3 text-xs");
  top.append(el("span", "font-mono text-[12px]", c.name), el("span", `font-medium ${c.passed ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`, c.passed ? "passed" : "failed"));
  if (blocks > 1) top.append(el("span", "text-slate-500", `block ${c.block}`));
  top.append(el("span", "ml-auto tabular-nums text-slate-500", fmtDur(c.duration_ms)));
  node.append(top, c.output == null ? el("p", "mt-2 text-xs text-slate-500", "Output unavailable: the log file is gone or cannot be read.") : pre(plain(c.output) || "(no output)", `mt-2 ${c.passed ? "" : "border-l-2 border-l-rose-500"}`));
  return node;
}

// `body` is what the attempt's own request answered; `shown` is {key, opened}: the attempt's key and the checks the owner toggled.
export function result(a, body, shown) {
  const box = el("div", `${BLOCK} flex flex-col gap-5`);
  const st = STATE[a.state];
  const summary = el("div");
  summary.append(label("Conclusion"), callout(a.state === "failed" ? "border-rose-500" : a.state === "running" ? "border-sky-500" : "border-emerald-500", null, body.result.summary));
  box.append(summary);
  if (body.result.answer) box.append(answer(body.result.answer));
  if (body.result.checks.length) {
    const wrap = el("div");
    wrap.append(label(`Checks · ${body.result.checks.length} · the end of each log, failed ones first`));
    const blocks = new Set(body.result.checks.map((c) => c.block)).size;
    const sorted = [...body.result.checks].sort((x, y) => x.passed - y.passed);
    for (const c of sorted) wrap.append(check(c, blocks, shown));
    box.append(wrap);
  } else if (body.result.output) {
    const out = el("div");
    out.append(label("Output"), pre(body.result.output, "border-l-2 border-l-rose-500"));
    box.append(out);
  }
  if (a.state === "running") box.append(el("p", "text-xs text-slate-500", `${st.label}: the result is written when the attempt ends.`));
  return box;
}

export function prompt(a, body) {
  const box = el("div", BLOCK);
  if (!body.input) {
    box.append(el("p", "text-sm text-slate-500", "No prompt: this step runs commands, not the agent."));
    return box;
  }
  box.append(label(`Input sent to the agent · ${body.input.length} characters`), pre(body.input, "max-h-none"));
  return box;
}
