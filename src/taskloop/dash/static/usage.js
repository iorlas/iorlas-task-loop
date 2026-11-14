// One presentation of the server's attempt counts and step/task totals.
import { el } from "./ui.js";

const fields = [["fresh", "fresh input"], ["cached", "cached input"], ["output", "output"], ["turns", "reported turns"]];
const number = new Intl.NumberFormat("en-US");
const explanation = "A turn is one model request and its reply. Tool calls are not turns. "
  + "Historical values retain the harness's earlier counts. Codex falls back to completed invocations "
  + "when model-request usage is unavailable.";

export function usageText(usage, label = "Tokens", total = false) {
  if (!usage || fields.every(([key]) => usage[key] == null)) return `${label} · not reported`;
  const counts = fields.map(([key, name]) => `${name} ${usage[key] == null ? "not reported" : number.format(usage[key])}`);
  if (total && usage.complete < usage.attempts) {
    counts.push(`reported values only; ${usage.complete}/${usage.attempts} attempts complete`);
  }
  return `${label} · ${counts.join(" · ")}`;
}

export function usageNode(usage, label = "Tokens", total = false) {
  const node = el("span", "block text-xs tabular-nums text-slate-500 dark:text-slate-400", usageText(usage, label, total));
  node.title = explanation;
  return node;
}
