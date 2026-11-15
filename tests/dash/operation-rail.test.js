import { rail } from "../../src/taskloop/dash/static/rail.js";

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const attempt = (step, n = 1, extra = {}) => ({ step, n, state: "succeeded", summary: "collected", ...extra });
const operation = (id, step, n, kind, state = "completed", extra = {}) => ({
  operation: id, step, n, kind, state, past: false, elapsed_ms: 1250,
  started_at: "2026-11-14T10:00:00Z", ...extra,
});

export async function operationRail() {
  const fixture = document.getElementById("fixture");
  const task = { id: "operations", column: "landed" };
  const attempts = [attempt("implement"), attempt("verification", 1, { summary: "verified" }),
    attempt("checks"), attempt("implement", 2)];
  const operations = [operation("commit-failed", "implement", 1, "commit", "failed"),
    operation("commit-retry", "implement", 1, "commit"), operation("publication", "implement", 1, "publish", "uncertain"),
    operation("start", "checks", 1, "checks-start", "active", { elapsed_ms: null, started_at: "2026-11-14T09:00:00Z" }),
    operation("again", "implement", 2, "commit", "completed", { started_at: "2026-11-14T08:00:00Z" })];
  const clicked = [], selected = { step: "verification", n: 1 };
  const mount = (list = attempts, values = operations) => {
    const node = rail(list, task, selected, (step, n) => clicked.push(`${step}/${n}`), {}, [], values);
    fixture.replaceChildren(node);
    return node;
  };
  let node = mount();
  const rows = [...node.querySelectorAll(":scope > ol > li")];
  assert(rows.map((li) => li.dataset.operation ?? li.querySelector("button > span > span")?.textContent)
    .join("|").startsWith("Implement|commit-failed|commit-retry|publication|start|Check|Implement|again"),
  "operations stay with owners despite reversed wall timestamps and checks without start times");
  assert(rows[0].querySelector("button[aria-pressed=true]"), "verification stays attached before operations");
  assert(node.querySelectorAll("[data-operation]").length === 5, "every retry has its own row");
  assert([...node.querySelectorAll("[data-operation]")].every((li) => !li.querySelector("button")), "operations are explanatory");
  assert(node.querySelector('[data-operation="commit-failed"]').textContent.includes("Failed"), "failure has words");
  assert(node.querySelector('[data-operation="publication"]').textContent.includes("Result unconfirmed"), "uncertainty has words");
  assert(node.querySelector('[data-operation="commit-retry"]').textContent.includes("1.3s"), "saved measurement is displayed");
  const incomplete = node.querySelector('[data-operation="start"]');
  assert(incomplete.textContent.includes("Completion unrecorded") && incomplete.textContent.includes("Duration unavailable"),
    "incomplete start cannot invent zero duration or a live clock");
  assert(!incomplete.querySelector("[data-since], [data-elapsed]"), "incomplete evidence does not tick");
  rows[0].querySelector("button[aria-pressed=true]").click();
  rows[5].querySelector("button").click();
  assert(clicked.join("|") === "verification/1|checks/1", "existing routes remain selectable");
  assert(mount(attempts, []).querySelectorAll("[data-operation]").length === 0, "missing evidence adds no placeholders");

  const history = attempts.map((a) => ({ ...a, past: true }));
  selected.step = "land"; selected.n = 0;
  node = mount(history, operations.map((o) => ({ ...o, past: true })));
  const heading = node.querySelector("summary");
  assert(!node.querySelector("details").open, "operation history folds with its owner");
  for (const text of ["Commit · Failed", "Publish · Result unconfirmed", "Start checks · Completion unrecorded"]) {
    assert(heading.textContent.includes(text), `folded summary retains ${text}`);
  }
  node.querySelector("details").open = true;
  await new Promise((resolve) => setTimeout(resolve, 0));
  node = mount(history);
  assert(node.querySelector("details").open, "disclosure survives operation redraw");
  assert(node.querySelectorAll("details [data-operation]").length === 5, "all operations stay inside history");
  const failedVerification = history.map((a) => a.step === "verification"
    ? { ...a, state: "failed", summary: "uncommitted:unsafe" } : a);
  node = mount(failedVerification);
  assert(node.querySelector("summary").textContent.includes("earlier failure"), "operation summaries retain verification failures");
}
