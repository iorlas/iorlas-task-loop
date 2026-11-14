// Load owner-attention.html in Chromium with --allow-file-access-from-files, or from a static server.
const results = document.getElementById("results");
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const question = "Which database?\nUse <img src=x onerror=alert(1)>?\n" + "Long question ".repeat(40);
const explanation = "The agent did not finish before its deadline.\nSee <img src=x onerror=alert(1)>.";
const card = (id, minute, extra = {}) => ({
  id, title: id, column: "held", attempt: 1, slot: "s1", hold_cause: "branch_moved",
  step_started_at: "2026-11-14T10:00:00Z", last_activity_at: `2026-11-14T10:${minute}:00Z`, ...extra,
});
const mixed = [card("hold-old", "03"), card("hold-new", "04", {
  hold_cause: "failed:run:timeout", hold_explanation: explanation,
}),
  card("ask-old", "01", { ask: true, question }),
  card("ask-new", "02", { ask: true, question: "Which region?\nChoose one." }),
  card("running", "05", { column: "implement", ask: true })];
let snapshot = { slots: ["s1", "s2"], tasks: mixed };
let stream;
window.fetch = async (url) => {
  let data;
  if (url === "/api/board") data = snapshot;
  else if (url.endsWith("/tracker")) data = null;
  else if (url.startsWith("/api/tasks/")) {
    const task = snapshot.tasks.find((t) => t.id === url.split("/").at(-1));
    data = { task, attempts: [], step_usage: {}, usage: {} };
  } else throw new Error(`Unexpected request: ${url}`);
  return { ok: true, json: async () => structuredClone(data) };
};
window.EventSource = class extends EventTarget {
  constructor(url) {
    super();
    assert(url === "/api/events", "Expected the existing stream endpoint");
    stream = this;
  }
};
const send = (message) => stream.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
const node = (id) => document.querySelector(`article[data-id="${id}"]`);
const ids = (parent) => [...parent.querySelectorAll("article")].map((n) => n.dataset.id).join(",");
function summary(asks, held) {
  const text = document.getElementById("summary").textContent;
  assert(text.includes(`${asks} need you`) && text.includes(`${held} held`), `Wrong summary: ${text}`);
}
function placement() {
  assert(ids(node("ask-old").parentNode) === "ask-new,ask-old,hold-new,hold-old", "Asks first, then recency in each group");
}
async function resync(tasks) {
  snapshot = { ...snapshot, tasks };
  send({ kind: "resync" });
  await tick();
}
function questions() {
  const body = [...node("ask-old").querySelectorAll("p")].find((p) => p.textContent === question);
  assert(body && body.getClientRects().length, "Complete question visible without opening the drawer");
  assert(!node("ask-old").querySelector("img"), "HTML-shaped question is text");
  assert(getComputedStyle(body).whiteSpace === "pre-wrap", "Question line breaks preserved");
  assert(getComputedStyle(body).overflowWrap === "break-word", "Long question wraps");
  assert(getComputedStyle(body).webkitLineClamp === "none", "Question is not clamped");
  assert(node("ask-new").textContent.includes("Which region?\nChoose one."), "Each ask has its own question");
  assert(!node("ask-old").textContent.includes("Factory problem:"), "An agent ask is not a factory problem");
  fault(node("hold-new"));
  assert(node("hold-old").textContent.includes("Factory problem: branch_moved"), "Unknown cause stays visible");
  assert(node("hold-old").textContent.includes("Explanation unavailable:"), "Missing explanation has explicit fallback");
}

function fault(parent, text = explanation) {
  const heading = [...parent.querySelectorAll("p")].find((p) =>
    p.textContent === "Factory problem: The agent did not finish in time");
  assert(heading?.title === "failed:run:timeout", "Readable factory problem label keeps raw cause on hover");
  const body = [...parent.querySelectorAll("p")].find((p) => p.textContent === text);
  assert(body && body.getClientRects().length, "Factory explanation is visible");
  assert(getComputedStyle(body).whiteSpace === "pre-wrap", "Explanation preserves line breaks");
  assert(!parent.querySelector("img"), "HTML-shaped explanation is text");
  assert(!parent.textContent.includes("Needs you"), "Factory problem is distinguishable from an agent ask");
}

async function drawers() {
  node("hold-new").click();
  await tick();
  fault(document.getElementById("drawer"));
  const revised = `${explanation}\nThe deadline was confirmed.`;
  send({ kind: "task", task: { ...mixed[1], hold_explanation: revised } });
  await tick();
  fault(node("hold-new"), revised);
  fault(document.getElementById("drawer"), revised);
  node("ask-old").click();
  await tick();
  const drawer = document.getElementById("drawer");
  assert(drawer.textContent.includes("Needs you") && drawer.textContent.includes(question), "Drawer preserves agent question");
  assert(!drawer.textContent.includes("Factory problem:") && !drawer.querySelector("img"), "Drawer ask is safe and distinct");
  document.getElementById("backdrop").click();
}

try {
  await import("../../src/taskloop/dash/static/app.js");
  for (let n = 0; !stream && n < 100; n++) await tick();
  assert(stream, "App subscribed to stream");
  for (const theme of ["light", "dark"]) {
    document.documentElement.className = theme;
    await resync(mixed);
    for (const layout of ["view-columns", "view-lanes"]) {
      document.getElementById(layout).click();
      summary(2, 4);
      placement();
      questions();
      await drawers();
      await resync(mixed);
      if (layout === "view-lanes") {
        assert(node("running").parentNode !== node("ask-old").parentNode, "Slot cells preserve step columns");
      }
    }
    send({ kind: "task", task: { ...mixed[3], question: null } });
    assert(node("ask-new").textContent.includes("Question unavailable"), "Missing question has an explanation");
    summary(2, 4);
    send({ kind: "task", task: { ...mixed[3], column: "implement" } });
    summary(1, 3);
    assert(!node("ask-new").textContent.includes("Needs you"), "Leaving Held removes ask treatment");
    send({ kind: "gone", id: "ask-old" });
    summary(0, 2);
    assert(!node("ask-old"), "Removed ask disappears");
    await resync(mixed.slice(0, 2));
    summary(0, 2);
    assert(!node("ask-new") && !node("running"), "Resync drops missing cards");
    await resync(mixed);
    summary(2, 4);
    placement();
  }
  results.textContent = "PASS: owner attention and factory faults, board and drawer, explanation updates, both layouts and themes";
} catch (error) {
  results.textContent = `FAIL: ${error.stack ?? error}`;
  throw error;
}
