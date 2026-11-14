// Load rail.html from a static server or Chromium with --allow-file-access-from-files. No dependencies needed.
import { rail, changeReason, lasted, verifyTitle } from "../../src/taskloop/dash/static/rail.js";
import { say, wordNode } from "../../src/taskloop/dash/static/words.js";
import { COLUMNS, STATE, el, position, quietSpan, tick as updateTime } from "../../src/taskloop/dash/static/ui.js";
import { result } from "../../src/taskloop/dash/static/result.js";
import { lines, setNote } from "../../src/taskloop/dash/static/lines.js";
import { initDrawer, openDrawer, closeDrawer } from "../../src/taskloop/dash/static/drawer.js";
import { taskView } from "../../src/taskloop/dash/static/taskview.js";
import { usageText } from "../../src/taskloop/dash/static/usage.js";

const fixture = document.getElementById("fixture");
const results = document.getElementById("results");
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const attempt = (step, n = 1, extra = {}) => ({ step, n, state: "succeeded", summary: "collected", started_at: null, ended_at: null, feed: [], ...extra });
const verify = (n = 37, extra = {}) => attempt("verification", n, { summary: "verified", ...extra });
const task = { id: "tl-test", title: "Compact rail fixture", column: "landed", attempt: 1 };
const healthy = () => [attempt("plan"), verify(), attempt("implement"), verify(38), attempt("checks", 1, { summary: "passed" })];
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const button = (root, text) => [...root.querySelectorAll("button")].find((b) => b.textContent === text);
const marks = (root) => [...root.querySelectorAll("button[aria-label]")];
const primary = (root) => [...root.querySelectorAll(":scope > ol > li")];
function mount(list, t = task, selected = {}, select = () => {}) {
  const node = rail(list, t, selected, select);
  fixture.replaceChildren(node);
  return node;
}

function healthyRows() {
  const clicks = [];
  const node = mount(healthy(), task, { step: "verification", n: 38 }, (...args) => clicks.push(args));
  assert(primary(node).length === 4 && button(node, "Check—"), "healthy task: Plan, Implement, Check, Land");
  assert(marks(node).length === 2 && marks(node).every((b) => b.textContent === "✓"), "success marks attached to agents");
  assert(!node.textContent.includes("attempt 1") && !node.textContent.includes("Factory checked"), "no routine attempt/verification text");
  assert(!node.querySelector("button button"), "no nested buttons");
  assert(marks(node)[1].getAttribute("aria-pressed") === "true", "selected verification has an indication");
  assert(marks(node)[1].getAttribute("aria-label").includes("Implement"), "accessible name identifies its agent step");
  marks(node)[1].focus();
  assert(document.activeElement === marks(node)[1], "mark independently focusable");
  marks(node)[1].click();
  assert(clicks[0].join("/") === "verification/38", "verification number need not match agent attempt");
  button(node, "Plan—").click();
  assert(clicks[1].join("/") === "plan/1", "step button selects its own result");
}

function verificationStates() {
  for (const code of ["verified", "reused", "unsettled:unsafe", "rejected:paths", "rejected:plan_rule"]) {
    const failed = !["verified", "reused"].includes(code);
    const selected = [];
    const node = mount([attempt("plan", 1, { state: failed ? "failed" : "succeeded", summary: failed ? "verification" : "verified" }), verify(42, { summary: code, state: failed ? "failed" : "succeeded" })], task, {}, (...args) => selected.push(args));
    assert(marks(node)[0].textContent === (failed ? "✗" : "✓"), code);
    marks(node)[0].click();
    if (failed) {
      const why = [...node.querySelectorAll("button")].find((b) => b.textContent.startsWith("Not committed:"));
      assert(why && !why.textContent.includes("Not committed: Not committed:"), "one rejection prefix");
      assert(why.title.includes(code), "raw failure code in hover");
      assert(!node.textContent.includes("The factory's check of the answer failed"), "verification failure not duplicated on agent row");
      why.click();
    }
    assert(selected.every((args) => args.join("/") === "verification/42"), "all failure controls select Result");
  }
  let node = mount([attempt("plan"), verify(4, { state: "running", summary: "pending" })]);
  assert(marks(node)[0].textContent === "…" && !node.textContent.includes("Not committed:"), "pending neutral");
  node = mount([attempt("plan"), verify(4, { state: "failed", summary: "pending" })]);
  assert(node.textContent.includes("verification outcome was not recorded"), "terminal missing outcome truthful");
  node = mount([attempt("plan")]);
  assert(!marks(node).length, "absent verification has no invented mark");
  node = mount([attempt("checks"), verify()]);
  assert(!marks(node).length, "verification never attached to Checks");
  node = mount([attempt("checks", 2, { state: "failed", summary: "failed:test:lint" })]);
  assert(node.textContent.includes("Checks failed: lint"), "other step failures stay readable");
}

function gaps() {
  const end = "2026-11-14T10:00:00Z";
  for (const seconds of [119, 120]) {
    const list = [attempt("plan", 1, { ended_at: end }), verify(), attempt("implement", 1, { started_at: new Date(Date.parse(end) + seconds * 1000).toISOString() })];
    const node = mount(list);
    assert(node.textContent.includes("Factory work") === (seconds === 120), `gap boundary ${seconds}`);
    assert(node.querySelectorAll("li[title]")[1].title.includes("Approximate elapsed gap"), "short gaps stay in hover");
    assert(!node.textContent.includes("idle"), "no idle rows");
  }
  for (const start of [null, "invalid", "2026-11-14T09:59:00Z"]) {
    const node = mount([attempt("plan", 1, { ended_at: end }), attempt("implement", 1, { started_at: start })]);
    assert(!node.textContent.includes("Factory work") && !node.textContent.includes("NaN"), "invalid gap omitted");
  }
  const node = mount(healthy(), { ...task, column: "land", land: "manual",
    status_note: "waiting for land: waits for a person; the profile says land: manual" });
  assert(node.textContent.includes("land: manual") && !node.textContent.includes("idle"), "Land keeps policy, no idle line");
  for (const [land, status_note] of [["unknown", "waiting for land: landing policy is unavailable"],
    ["waiting", "waiting for land: waits for the factory"]]) {
    const waiting = mount(healthy(), { ...task, column: "land", land, status_note });
    assert(waiting.textContent.includes(status_note), "Land uses the server's policy explanation");
    assert(!waiting.textContent.includes("next round"), "Land makes no unconditional timing promise");
  }
  assert(lasted(attempt("plan", 1, { started_at: "bad", ended_at: end })) === "—", "invalid attempt timing omitted");
}

const repeat = (step, n, extra = {}) => attempt(step, n, { after: "repeat", repeat_of: n - 1, reason: "unsafe", ...extra });
const restart = (n, extra = {}) => attempt("plan", n, { after: "restart_at_plan", reason: "restarted at plan", ...extra });
function restartsAndRepeats() {
  const today = new Date(); today.setHours(20, 38, 0, 0);
  const before = new Date(today.getTime() - 501000);
  let node = mount([attempt("plan", 1, { ended_at: before.toISOString() }), restart(2, { started_at: today.toISOString() })]);
  let row = [...node.querySelectorAll("button")].find((b) => b.textContent.startsWith("Restarted at plan"));
  assert(row.textContent === "Restarted at plan · 20:38 · waited 8m 21s", "today restart is short, contains wait");
  assert(row.title.startsWith("Reason not recorded"), "placeholder not a cause");
  assert(!node.textContent.includes("Factory work"), "restart gap never factory work");
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  node = mount([restart(2, { started_at: yesterday.toISOString(), reason: "Owner changed scope" })]);
  row = [...node.querySelectorAll("button")].find((b) => b.textContent.startsWith("Restarted at plan"));
  assert(row.textContent.includes(yesterday.toLocaleString([], { month: "short", day: "numeric" })), "past local date shown");
  assert(row.title === "Owner changed scope", "genuine restart explanation preserved");
  node = mount([restart(2)]);
  assert(button(node, "Restarted at plan"), "no invented timestamp");
  assert(changeReason(restart(2)) === "Reason not recorded", "restart detail normalizes placeholder too");
  for (const step of ["plan", "implement"]) {
    node = mount([attempt(step, 1, { ended_at: before.toISOString() }), repeat(step, 2, { started_at: today.toISOString() })]);
    const tag = [...node.querySelectorAll("span")].find((s) => s.textContent === "Repeat");
    assert(tag?.title.includes("attempt 1: A listed path is unsafe") && tag.title.includes("8m 21s"),
      "readable repeat tag with previous attempt and gap");
    assert(node.textContent.includes("attempt 2"), "repeated attempt numbered");
    assert(!node.textContent.includes("Factory work") && !node.textContent.includes("Restarted"), "repeat adds no row or factory gap");
    assert(!node.querySelector("details"), "repeat never starts another group");
  }
  const clicks = [];
  node = mount([attempt("implement"), verify(), attempt("checks", 1, { state: "failed", summary: "failed:test:lint" }),
    repeat("implement", 2, { reason: "failed_check" })], task, {}, (...args) => clicks.push(args));
  const tag = [...node.querySelectorAll("span")].find((s) => s.textContent === "Repeat");
  assert(tag.title.includes("The checks failed") && marks(node).length === 1, "check-driven repeat invents no verification cause");
  [...node.querySelectorAll("button")].find((b) => b.textContent.includes("Checks failed: lint")).click();
  assert(clicks[0].join("/") === "checks/1", "failed Check result remains reachable");
}

function reviewed() {
  const past = healthy().map((a) => ({ ...a, past: true }));
  return [...past, restart(2), verify(39), attempt("implement", 2, { state: "failed", summary: "verification" }), verify(40, { state: "failed", summary: "unsettled:unsafe" }),
    repeat("implement", 3, { led_by: 40 }), verify(41), attempt("checks", 2, { summary: "passed" })];
}
async function pastRuns() {
  const selected = { step: "checks", n: 2 };
  let node = mount(reviewed(), task, selected);
  assert(node.querySelector("summary").textContent === "History 1 · Plan ✓ · Implement ✓ · Check ✓",
    "past status from actual results");
  assert(node.querySelector("summary").title.includes("every attempt and verification result"), "history tooltip uses attempt");
  assert(!node.querySelector("details").open && primary(node).length === 6, "reviewed shape folds past, about eight lines including failure");
  node.querySelector("details").open = true;
  await tick();
  node = mount(reviewed(), task, selected);
  assert(node.querySelector("details").open, "expanded group survives redraw");
  selected.step = "verification"; selected.n = 37;
  node = mount(reviewed(), task, selected);
  assert(node.querySelector("details").open && node.querySelector("[aria-pressed=true]"), "selected verification revealed");
  await tick();
  node.querySelector("details").open = false;
  await tick();
  node = mount(reviewed(), task, selected);
  assert(!node.querySelector("details").open, "person may close selected group until selection changes");
  const history = [attempt("plan", 1, { past: true }), verify(1, { state: "failed", summary: "unsettled:unsafe", past: true }),
    repeat("plan", 2, { past: true }), verify(2, { past: true }), restart(3, { past: true }), verify(3, { past: true }), restart(4)];
  node = mount(history);
  const summaries = [...node.querySelectorAll("summary")];
  assert(summaries.length === 2 && summaries[1].textContent.startsWith("History 2"), "restart boundaries split past history");
  assert(summaries[0].textContent.includes("Plan ✓ (earlier failure)"), "success never hides earlier failures");
  node = mount([attempt("plan", 1, { past: true })], { ...task, column: "waiting" });
  assert(!node.textContent.includes("pending") && !primary(node).length, "entirely past waiting task invents no steps");
  assert(node.querySelector("summary").textContent.includes("Plan …"), "unverified answer never marked committed");
}

async function drawerSelection() {
  fixture.replaceChildren();
  const list = reviewed();
  const requested = [];
  const verification = { of_step: "implement", of: 2, listed: ["src/link.py"], listing: ["src/link.py"], result: "unsettled:unsafe", checks: [{ name: "Path must be a plain file", state: "failed" }] };
  const source = {
    detail: async () => ({ task, attempts: list }),
    tracker: async () => ({ fields: null, comments: [] }),
    body: async (id, step, n) => {
      requested.push(`${step}/${n}`);
      return { input: "Implement the task", added: [], result: { summary: step === "verification" ? "unsettled:unsafe" : "passed", checks: [], verification: step === "verification" ? verification : null } };
    },
  };
  initDrawer(source, new Map([[task.id, task]]));
  await openDrawer(task.id); await tick();
  const drawer = document.getElementById("drawer");
  drawer.querySelector("#rail details").open = true;
  button(drawer, "Prompt").click();
  assert(drawer.querySelector("#rail details").open, "disclosure survives redraw before toggle event fires");
  await tick();
  for (const tab of ["Lines", "Prompt", "Result"]) {
    const row = [...drawer.querySelectorAll("#rail button")].find((b) => b.textContent.includes("Implementattempt 3"));
    row.click(); await tick();
    assert(drawer.querySelector("section h3").textContent.includes("Implement, attempt 3"), "selected attempt title");
    assert(drawer.querySelector("section").textContent.includes("Success"), "successful attempt badge");
    button(drawer, tab).click(); await tick();
    assert(drawer.textContent.includes("A listed path is unsafe"), "selected repeat reason translated");
    const mark = marks(drawer).find((b) => b.textContent === "✗");
    mark.click(); await tick();
    assert(drawer.querySelector("section h3").textContent.includes("Check of Implement attempt 2"), "verification title");
    assert(drawer.querySelector("section").textContent.includes("Failure"), "failed attempt and validation badges");
    assert(mark.getAttribute("aria-label").includes("Implement attempt 2"), "accessible verification reference");
    assert(drawer.textContent.includes("Named by the failed check") && drawer.textContent.includes("src/link.py") && drawer.textContent.includes("Path must be a plain file"), `${tab} → verification Result includes rule and listing`);
    assert(drawer.querySelector("#rail [aria-pressed=true]"), "verification selection survives body redraw");
  }
  assert(requested.includes("verification/40"), "real verification endpoint selected");
  closeDrawer();
}

function words() {
  for (const [code, expected] of [
    ["needs_owner", "The agent needs your decision"],
    ["failed:test:failed", "Checks failed: test"],
    ["answer:schema_invalid", "The agent's answer was in the wrong format"],
  ]) {
    assert(say(code) === expected, `${code} exact label`);
    const word = wordNode(el, code);
    assert(word.textContent === expected && word.title === code, `${code} label and raw-code hover`);
    const item = attempt("implement", 1, { state: "failed", summary: code });
    const node = mount([item]);
    const summary = node.querySelector(`button span[title="${code}"]`);
    assert(summary?.textContent === expected, `${code} failed rail label and raw-code hover`);
    const body = { result: { summary: code, checks: [] } };
    const view = result(item, body, { key: "implement/1", opened: new Map() });
    fixture.replaceChildren(view);
    const conclusion = view.querySelector(`p[title="${code}"]`);
    assert(conclusion?.textContent === expected, `${code} conclusion label and raw-code hover`);
  }
  const item = attempt("implement", 1, { state: "failed", summary: "needs_owner" });
  const body = { result: { summary: "needs_owner", checks: [], answer: {
    disposition: "needs_owner", text: '{"explanation":"Owner decision required"}', truncated: false,
  } } };
  const view = result(item, body, { key: "implement/1", opened: new Map() });
  fixture.replaceChildren(view);
  const disposition = view.querySelector('span[title="needs_owner"]');
  assert(disposition?.textContent === "The agent needs your decision", "answer badge label and raw-code hover");
  for (const code of ["verification", "unsafe", "ignored", "uncommitted", "failed_check", "test:lint"]) assert(say(code) !== code, `${code} readable`);
  assert(say("unknown:new") === "unknown:new" && say("Owner changed scope") === "Owner changed scope", "unknown codes/prose preserved");
  assert(wordNode(el, "unsafe").title === "unsafe", "raw code hover retained");
  assert(say("run:unknown") === "The agent attempt failed: unknown", "agent failure family keeps its tail");
}

function vocabulary() {
  assert(COLUMNS.find((c) => c.id === "checks").label === "Check", "step label singular");
  assert(COLUMNS.find((c) => c.id === "held").label === "Hold", "hold label");
  assert(STATE.succeeded.label === "Success" && STATE.failed.label === "Failure", "outcome labels");
  assert(position({ column: "implement", attempt: 3 }) === "step 2 of 4 · attempt 3", "board attempt position");
  assert(position({ column: "land", attempt: 3 }) === "step 4 of 4", "land adds no numbered attempt");
  const list = [attempt("implement", 2), verify(88)];
  assert(verifyTitle(list, list[1]) === "Check of Implement attempt 2", "verification names the agent attempt");
  const item = attempt("checks", 2, { feed: [
    { type: "step", step: "checks", attempt: 2, at: "2026-11-14T10:00:00Z" },
    { type: "check", name: "try external command", passed: true, duration_ms: 1000, at: "2026-11-14T10:00:01Z" },
    { type: "check", name: "lint", passed: false, duration_ms: 1000, at: "2026-11-14T10:00:02Z" },
  ] });
  fixture.replaceChildren(lines(item));
  assert(fixture.textContent.includes("Check attempt 2 started"), "feed uses the step's display label");
  assert(fixture.textContent.includes("Success") && fixture.textContent.includes("Failure"), "feed check outcomes");
  assert(fixture.textContent.includes("try external command"), "external check name preserved");
  setNote({ ...item, feedError: "offline" });
  assert(document.getElementById("feednote").textContent === "Feed stopped: offline. Reconnecting.", "feed reconnection");
  const body = { result: { summary: "passed", checks: [
    { name: "build", passed: true, duration_ms: 1000, block: 1, output: "try raw output" },
    { name: "lint", passed: false, duration_ms: 1000, block: 1, output: "error" },
  ] } };
  const view = result(item, body, { key: "checks/2", opened: new Map() });
  const checks = [...view.querySelectorAll("details")];
  assert(checks[0].querySelector("summary").textContent.includes("Failure") && checks[0].open, "failed check open first");
  assert(checks[1].querySelector("summary").textContent.includes("Success") && !checks[1].open, "successful check folded");
  assert(view.textContent.includes("Checks · 2") && view.textContent.includes("try raw output"), "collection and raw output");
  let reloads = 0;
  const task = taskView({ state: "failed", error: "offline" }, () => reloads++);
  button(task, "Reload task").click();
  assert(reloads === 1, "reload reads tracker through the existing callback");
  const clock = Date.now;
  Date.now = () => Date.parse("2026-11-14T10:15:00Z");
  try {
    const activity = quietSpan("2026-11-14T10:13:01Z");
    assert(activity.hidden, "activity age hidden under two minutes");
    activity.dataset.quiet = "2026-11-14T10:13:00Z";
    updateTime(activity);
    assert(!activity.hidden && activity.textContent === "Last activity 2m 00s ago", "activity age at two minutes");
    assert(activity.querySelector(".bg-amber-500"), "two-minute activity colour retained");
    activity.dataset.quiet = "2026-11-14T10:00:00Z";
    updateTime(activity);
    assert(activity.textContent === "Last activity 15m 00s ago" && activity.querySelector(".bg-rose-500"),
      "fifteen-minute activity wording and colour");
  } finally {
    Date.now = clock;
  }
}

async function usage() {
  const counts = { fresh: 49773, cached: 496768, output: 2375, turns: 1, attempts: 1, complete: 1 };
  const sum = { ...counts, attempts: 2, complete: 1 };
  const text = usageText(counts);
  for (const value of ["fresh input 49,773", "cached input 496,768", "output 2,375", "reported turns 1"]) {
    assert(text.includes(value), `exact reported count: ${value}`);
  }
  assert(usageText({ fresh: 0, cached: 0, output: 0, turns: 0 }).includes("output 0"), "reported zero stays zero");
  assert(usageText({}).includes("not reported"), "absent attempt usage");
  assert(usageText({ ...counts, turns: null }).includes("reported turns not reported"), "missing turns independent of tokens");
  const list = [attempt("plan", 1, { usage: counts }), repeat("plan", 2, { usage: {} })];
  const node = rail(list, task, {}, () => {}, { plan: sum });
  fixture.replaceChildren(node);
  assert(node.textContent.includes("Step total") && node.textContent.includes("reported values only"), "partial step total visible");
  assert(primary(node)[0].title.includes(text) && primary(node)[0].title.includes("1/2 attempts complete"), "hover has attempt and step total");
  assert(primary(node)[1].title.includes("not reported"), "missing report in attempt hover");
  assert(node.querySelector("span[title*='Repeat of']").title.includes("unsafe"), "repeat explanation retained with usage");
  for (const tracker of [{ state: "loading" }, { state: "failed", error: "offline" }, { state: "none" }]) {
    const view = taskView(tracker, () => {}, sum);
    assert(view.textContent.includes("Task total") && view.textContent.includes("1/2 attempts complete"), "tracker-independent task total");
  }
  const run = { harness: "Codex", provider: "OpenAI", model: "chosen", effort: "high", access: "full access" };
  const source = {
    detail: async () => ({ task, attempts: [attempt("plan", 1, { usage: counts, run })], step_usage: { plan: counts }, usage: counts }),
    tracker: async () => ({ fields: null, comments: [] }),
    body: async () => ({ input: "Plan", result: { summary: "passed", checks: [] } }),
  };
  initDrawer(source, new Map([[task.id, task]]));
  await openDrawer(task.id); await tick();
  const drawer = document.getElementById("drawer");
  const header = drawer.querySelector("section > div");
  assert(header.textContent.includes(text) && header.textContent.includes("end not recorded"), "attempt counts beside timing");
  assert(header.querySelector("span[title*='Codex completed turns']"), "reported turns explained in hover");
  assert(drawer.textContent.includes("Codex · OpenAI · chosen · high effort · full access"), "run context retained");
  assert(drawer.textContent.includes("Task total"), "task context total visible while inspecting attempt");
  button(drawer, "Task").click(); await tick();
  assert(drawer.textContent.includes("Task total") && !drawer.textContent.includes("not reported"), "task view retains total");
  closeDrawer();
  source.detail = async () => ({ task, attempts: [attempt("plan", 1, { usage: {}, run })], usage: {} });
  await openDrawer(task.id); await tick();
  assert(drawer.querySelector("section > div").textContent.includes("Tokens · not reported"), "missing attempt report in header");
  closeDrawer();
}

try {
  for (const test of [healthyRows, verificationStates, gaps, restartsAndRepeats, pastRuns, drawerSelection, words, vocabulary, usage]) {
    await test();
  }
  for (const dark of [false, true]) {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
    const node = mount(reviewed());
    assert(node.querySelector("button").getBoundingClientRect().height > 0, "theme renders buttons");
  }
  document.documentElement.classList.toggle("dark", location.hash === "#dark");
  document.documentElement.classList.toggle("light", location.hash !== "#dark");
  results.textContent = "PASS: 9 browser contracts, both themes";
  document.documentElement.dataset.result = "passed";
} catch (error) {
  results.textContent = `FAIL: ${error.stack}`;
  document.documentElement.dataset.result = "failed";
}
