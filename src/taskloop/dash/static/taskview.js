// The Task view of the drawer: the task as the tracker holds it. The tracker is read after the drawer opens, so this view has
// three states: loading (a skeleton), failed (the reason, and a retry) and ready.

import { ago, el, tag } from "./ui.js";
import { usageNode } from "./usage.js";

const prose = (text) => el("div", "whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200", text);
const heading = (text) => el("h4", "mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500", text);
const section = (title, text) => {
  const node = el("section");
  node.append(heading(title), prose(text));
  return node;
};
const bar = (width) => el("div", `h-3 animate-pulse rounded bg-slate-200 dark:bg-slate-700 ${width}`);

function skeleton() {
  const wrap = el("div", "flex min-w-0 flex-1 flex-col gap-3 px-6 py-5");
  wrap.append(el("p", "text-xs text-slate-500 dark:text-slate-400", "Loading the task from the tracker…"), bar("w-1/3"), bar("w-full"), bar("w-5/6"), bar("w-2/3"));
  return wrap;
}

function failure(message, retry) {
  const wrap = el("div", "flex flex-col items-start gap-3 px-6 py-5");
  wrap.append(el("p", "text-sm text-rose-700 dark:text-rose-300", `The tracker did not answer: ${message}`));
  const again = el("button", "rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 "
    + "dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800", "Reload task");
  again.type = "button";
  again.addEventListener("click", retry);
  wrap.append(again);
  return wrap;
}

// `tracker` is {state: "loading"} | {state: "failed", error} | {state: "none"} | {state: "ready", fields, comments}.
export function taskView(tracker, retry, usage) {
  const wrap = el("div", "flex min-h-0 flex-1 flex-col");
  const total = el("div", "px-6 pt-4");
  total.append(usageNode(usage, "Task total", true));
  wrap.append(total, trackerView(tracker, retry));
  return wrap;
}

function trackerView(tracker, retry) {
  if (tracker.state === "loading") return skeleton();
  if (tracker.state === "failed") return failure(tracker.error, retry);
  if (tracker.state === "none") return el("p", "px-6 py-5 text-sm text-slate-500", "The tracker has no such task.");
  const { fields: f, comments } = tracker;
  const wrap = el("div", "flex min-h-0 flex-1");
  const main = el("div", "flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto px-6 py-5");
  main.append(section("Description", f.description));
  for (const [title, text] of [["Acceptance criteria", f.acceptance], ["Design", f.design], ["Notes", f.notes]]) if (text) main.append(section(title, text));
  const thread = el("section", "border-t border-slate-200 pt-5 dark:border-slate-800");
  thread.append(heading(`Comments · ${comments.length}`));
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
