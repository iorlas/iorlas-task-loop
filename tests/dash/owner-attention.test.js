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
  card("running", "05", { column: "implement", status: "running", ask: true,
    duration: { execution: "running", number: 1, elapsed_ms: 7200000, quiet_ms: 900000, frozen: false } })];
let snapshot = { slots: ["s1", "s2"], tasks: mixed };
const backlog = "fixture/main";
const round = (at, extra = {}) => ({ at, backlog, move: "round", task: null, step: null, words: ["moves=0"], ...extra });
let now = Date.parse("2026-11-14T12:00:00Z");
Date.now = () => now;
let monotonic = 0;
Object.defineProperty(performance, "now", { value: () => monotonic, configurable: true });
const timers = [];
const interval = window.setInterval;
window.setInterval = (callback, ms) => {
  if (ms !== 1000) return interval(callback, ms);
  timers.push(callback);
  return 0;
};
const advance = (ms) => { now += ms; monotonic += ms; timers.forEach((callback) => callback()); };
let logSnapshot = { backlog, rows: [round("2026-11-14T10:00:00Z")] };
let logResponse = () => logSnapshot;
let boardError = null;
let logReads = 0;
let stream;
window.fetch = async (url) => {
  let data;
  if (url === "/api/board") {
    if (boardError) throw boardError;
    data = snapshot;
  } else if (url === "/api/log") {
    logReads++;
    data = await logResponse();
  } else if (url.endsWith("/tracker")) data = { fields: {
    description: "Fixture task", labels: [], depends_on: [],
    created_at: "2026-11-14T10:00:00Z", updated_at: "2026-11-14T10:00:00Z",
  }, comments: [] };
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
const send = (message) => {
  if (message.kind === "task") {
    snapshot.tasks = [...snapshot.tasks.filter((t) => t.id !== message.task.id), message.task];
  }
  stream.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) }));
};
const node = (id) => document.querySelector(`article[data-id="${id}"]`);
const ids = (parent) => [...parent.querySelectorAll("article")].map((n) => n.dataset.id).join(",");
function summary(asks, held) {
  const text = document.getElementById("summary").textContent;
  assert(text.includes(`${asks} need you`) && text.includes(`${held} on hold`), `Wrong summary: ${text}`);
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
  assert(drawer.textContent.includes("⛔ Hold"), "Drawer uses the shared Hold label");
  assert(drawer.textContent.includes("Needs you") && drawer.textContent.includes(question), "Drawer preserves agent question");
  assert(!drawer.textContent.includes("Factory problem:") && !drawer.querySelector("img"), "Drawer ask is safe and distinct");
  document.getElementById("backdrop").click();
}

async function boardWords() {
  const headings = [...document.querySelectorAll("#board h2")].map((h) => h.textContent);
  assert(headings.join("|") === "Waiting|Plan|Implement|Check|Land|Hold|Landed", "glossary column labels in both layouts");
  for (const status of ["queued", "abandoned"]) {
    const task = card(`waiting-${status}`, "00", { column: "waiting", status, slot: null,
      status_note: `${status}: no current work`, hold_cause: null });
    send({ kind: "task", task });
    const article = node(task.id);
    assert(article.textContent.includes(status === "queued" ? "Queued" : "Abandoned"), "waiting retains status explanation");
    assert(article.textContent.includes("Waiting since not recorded"), "unknown waiting start is explicit");
    assert(!article.querySelector("[data-quiet]"), "waiting adds no running-activity observation");
    article.click(); await tick();
    assert(document.getElementById("drawer").textContent.includes("Waiting"), "drawer shares Waiting label");
    document.getElementById("backdrop").click();
  }
  const heading = document.querySelector("#board h2").parentNode;
  assert(heading.title.includes("queued and abandoned") && !heading.title.includes("Approved"), "waiting membership help");
  assert(node("running").textContent.includes("step 2 of 4 · attempt 1"), "board position uses attempt");
  const activity = node("running").querySelector("[data-quiet]");
  const previous = activity.textContent;
  assert(previous.startsWith("Last activity ") && previous.endsWith(" ago"), "board activity age label");
  advance(60000);
  assert(activity.textContent !== previous && activity.textContent.endsWith(" ago"), "activity age still updates");
}

async function waitingStates() {
  const stamp = "2026-11-14T11:00:00Z";
  const waiting = [
    card("new-queued", "00", { column: "waiting", attempt: 0, status_note: "queued to start: no free slot" }),
    card("abandoned", "00", { column: "waiting", status: "abandoned", waiting_since: stamp,
      status_note: "abandoned: waits for approval" }),
    ...["manual", "waiting", "unknown"].map((land) => card(`land-${land}`, "00", {
      column: "land", land, waiting_since: stamp, status_note: `Awaiting land: ${land}`,
    })),
    card("checking", "00", { column: "checks" }),
    card("landing", "00", { column: "land", land: "landing" }),
  ];
  await resync([...mixed, ...waiting]);
  for (const task of waiting) {
    const article = node(task.id);
    assert(!article.querySelector("[data-quiet]"), `${task.id} has no agent quiet duration`);
    if (["checking", "landing"].includes(task.id)) {
      assert(!article.textContent.includes("Waiting since"), `${task.id} is active work`);
      continue;
    }
    assert(article.textContent.includes(task.status_note), `${task.id} names what it awaits`);
    article.click(); await tick();
    const drawer = document.getElementById("drawer");
    assert(drawer.textContent.includes(task.status_note), `${task.id} drawer explains wait`);
    if (task.waiting_since) {
      const time = article.querySelector("[data-waiting-since]");
      assert(time.title === stamp && time.textContent.startsWith("Waiting since"), "recorded start is visible");
      assert(drawer.querySelector("[data-waiting-since]").title === stamp, "drawer shares wait start");
      const before = time.textContent;
      advance(60000);
      assert(time.textContent !== before, "waiting age updates");
    } else assert(drawer.textContent.includes("Waiting since not recorded"), "new queued start is unknown");
    document.getElementById("backdrop").click();
  }
  assert(node("running").dataset.quietLevel === "long", "running warning is present before transition");
  for (const next of [waiting[0], mixed[0], waiting[2], waiting[5]]) {
    send({ kind: "task", task: { ...next, id: "running" } });
    assert(!node("running").querySelector("[data-quiet]") && !node("running").dataset.quietLevel,
      "leaving a running agent clears activity and warning border");
  }
  send({ kind: "task", task: mixed.at(-1) });
  assert(node("running").querySelector("[data-quiet]"), "returning to running restores activity age");
}

async function liveDurations() {
  const sample = { execution: "board-duration", number: 1, elapsed_ms: 119999, quiet_ms: 119999, frozen: false };
  const live = card("duration", "00", { column: "plan", status: "running", step_started_at: null, duration: sample });
  const publish = (duration) => send({ kind: "task", task: { ...live, duration } });
  publish(sample);
  const elapsed = () => node(live.id).querySelector("[data-duration]").textContent;
  const quiet = () => node(live.id).querySelector("[data-quiet]");
  assert(elapsed() === "1m 59s in step" && quiet().hidden, "projection works without a start timestamp; quiet below 120s");
  const savedWall = now;
  now += 86400000;
  advance(1);
  assert(elapsed() === "2m 00s in step" && node(live.id).dataset.quietLevel === "slow", "forward wall jump keeps amber threshold");
  assert(quiet().querySelector(".bg-amber-500"), "card amber dot");
  now -= 172800000;
  advance(1000);
  publish(sample);
  document.getElementById("view-lanes").click();
  assert(elapsed() === "2m 01s in step", "backward wall jump, duplicate and layout redraw keep progress");
  await resync([...mixed, { ...live, duration: { ...sample, number: 0, elapsed_ms: 0, quiet_ms: 0 } }]);
  assert(elapsed() === "2m 01s in step", "stale snapshot cannot restart receipt time");
  advance(778999);
  assert(node(live.id).dataset.quietLevel === "slow", "card stays amber at 899999ms");
  advance(1);
  assert(node(live.id).dataset.quietLevel === "long" && quiet().querySelector(".bg-rose-500"), "card turns red at 900000ms");
  publish({ ...sample, number: 2, elapsed_ms: 500000, quiet_ms: 500000 });
  assert(elapsed() === "15m 00s in step" && node(live.id).dataset.quietLevel === "long", "newer delayed sample preserves progress");
  publish({ ...sample, number: 3, elapsed_ms: 900000, quiet_ms: 0 });
  assert(quiet().hidden && !node(live.id).dataset.quietLevel, "new command evidence clears card severity");
  publish(sample);
  assert(quiet().hidden, "stale command evidence cannot restore severity");
  publish({ ...sample, execution: "board-next", elapsed_ms: 3000, quiet_ms: 0 });
  assert(elapsed() === "3.0s in step" && quiet().hidden, "new execution has its own receipt base");
  publish({ ...sample, execution: "board-next", number: 2, elapsed_ms: 900000, quiet_ms: 900000 });
  assert(node(live.id).dataset.quietLevel === "long", "warning before unavailable evidence");
  publish(null);
  send({ kind: "task", task: { ...live, duration: null, step_started_at: "1900-01-01T00:00:00Z" } });
  assert(!node(live.id).querySelector("[data-duration]"), "null stream receipt removes cached elapsed binding");
  assert(node(live.id).textContent.includes("Unknown duration"), "null stream receipt has explicit unknown elapsed");
  assert(quiet().textContent === "Last activity unknown" && !quiet().querySelector("span"), "unknown quiet has no dot");
  assert(!node(live.id).dataset.quietLevel && !/amber|rose/.test(quiet().className), "unknown quiet clears severity");
  await resync([...mixed, { ...live, duration: null }]);
  advance(86400000);
  assert(node(live.id).textContent.includes("Unknown duration"), "null snapshot stays unknown across ticks");
  const restored = { ...sample, execution: "board-next", number: 3, elapsed_ms: 1000000, quiet_ms: 900000 };
  publish(restored);
  assert(node(live.id).dataset.quietLevel === "long", "valid receipt restores warning");
  await resync([...mixed, { ...live, duration: null }]);
  assert(!node(live.id).dataset.quietLevel && quiet().textContent === "Last activity unknown", "null snapshot clears warning");
  publish({ ...restored, number: 4, quiet_ms: null });
  assert(quiet().textContent === "Last activity unknown" && !node(live.id).dataset.quietLevel, "unavailable quiet stays neutral");
  const final = { ...restored, number: 5, elapsed_ms: 3000, quiet_ms: null, frozen: true };
  publish(final);
  assert(elapsed() === "3.0s in step" && !quiet(), "smaller final value replaces live extrapolation without quiet");
  advance(86400000);
  publish(final);
  publish({ ...restored, number: 6 });
  assert(elapsed() === "3.0s in step" && !node(live.id).dataset.quietLevel, "ticks and later live receipt cannot change final elapsed");
  await resync([...mixed, { ...live, duration: final }]);
  document.getElementById("view-columns").click();
  assert(elapsed() === "3.0s in step" && !quiet(), "snapshot and redraw retain exact frozen duration");
  now = savedWall;
  await resync(mixed);
}

const healthText = () => document.getElementById("mode").textContent;
const health = (text) => assert(healthText().includes(text), `Expected ${text}: ${healthText()}`);
const transport = (kind) => stream.dispatchEvent(new Event(kind));
const logEvent = (row) => send({ kind: "log", row });
const reload = async () => { send({ kind: "resync" }); await tick(); };
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

const lifecycle = (word, extra = {}) => round("2026-11-14T12:00:00Z", { move: "rounds", words: [word], ...extra });
const stoppedNote = "Rounds last recorded as stopped; automatic landing awaits rounds resuming.";
const stopped = (expected) => assert(node("land-waiting").textContent.includes(stoppedNote) === expected,
  `Stopped explanation should be ${expected}: ${node("land-waiting").textContent}`);

async function stoppedRounds() {
  const waiting = ["waiting", "manual", "unknown", "landing"].map((land) => card(`land-${land}`, "00", {
    column: "land", land, status_note: `Awaiting land: ${land}`,
  }));
  logSnapshot.rows = [lifecycle("started"), lifecycle("stopped", { words: ["stopped", "interrupted"] })];
  await resync([...mixed, ...waiting]);
  stopped(true);
  health("No round in available log");
  for (const task of waiting.slice(1)) {
    assert(!node(task.id).textContent.includes(stoppedNote), `${task.land} explanation remains authoritative`);
    assert(node(task.id).textContent.includes(task.status_note), `${task.land} retains its explanation`);
  }
  for (const layout of ["view-lanes", "view-columns"]) {
    document.getElementById(layout).click();
    stopped(true);
  }
  for (const row of [lifecycle("started", { backlog: "other" }), lifecycle("wait", { at: "invalid" }),
    lifecycle("started", { at: "2026-02-30T12:00:00Z" }), lifecycle("warn"), round("2026-11-14T12:01:00Z")]) {
    logEvent(row);
    stopped(true);
  }
  for (const word of ["started", "wait"]) {
    logEvent(lifecycle(word));
    stopped(false);
    logEvent(lifecycle("stopped", { words: ["stopped", "abrupt"] }));
    stopped(true);
  }
  logEvent(lifecycle("started", { at: "2026-11-14T11:59:59Z" }));
  stopped(true);
  send({ kind: "task", task: { ...waiting[0], title: "Updated waiting task" } });
  stopped(true);
  send({ kind: "gone", id: "land-waiting" });
  send({ kind: "task", task: waiting[0] });
  stopped(true);
  logSnapshot.rows = [lifecycle("stopped"), lifecycle("started")];
  transport("open"); await tick();
  stopped(false);
  logSnapshot.rows = [lifecycle("stopped", { words: ["stopped", "abrupt"] })];
  await reload();
  stopped(true);
  for (const rows of [[], [lifecycle("stopped", { backlog: "other" })], [round("2026-11-14T12:01:00Z")]]) {
    logSnapshot.rows = rows;
    await reload();
    stopped(false);
  }
  logEvent(lifecycle("stopped"));
  logResponse = () => { throw new Error("fixture log failed"); };
  await reload();
  stopped(false);
  logResponse = () => logSnapshot;
}

async function stoppedRaces() {
  for (const word of ["started", "wait", "stopped"]) {
    const old = deferred();
    logResponse = () => old.promise;
    send({ kind: "resync" });
    logEvent(lifecycle(word));
    old.resolve({ backlog, rows: [lifecycle(word === "stopped" ? "started" : "stopped")] });
    await tick();
    stopped(word === "stopped");
  }
  const old = deferred();
  logResponse = () => old.promise;
  send({ kind: "resync" });
  logSnapshot.rows = [lifecycle("wait")];
  logResponse = () => logSnapshot;
  await reload();
  old.resolve({ backlog, rows: [lifecycle("stopped")] });
  await tick();
  stopped(false);
  const empty = deferred();
  logResponse = () => empty.promise;
  send({ kind: "resync" });
  logEvent(lifecycle("stopped"));
  empty.resolve({ backlog, rows: [] });
  await tick();
  stopped(true);
  const failed = deferred();
  logResponse = async () => { await failed.promise; throw new Error("fixture log failed"); };
  send({ kind: "resync" });
  logEvent(lifecycle("started"));
  failed.resolve();
  await tick();
  stopped(false);
  logResponse = () => logSnapshot;
}

async function healthStates() {
  now = Date.parse("2026-11-14T12:00:00Z");
  logSnapshot = { backlog, rows: [round("2026-11-14T10:00:00Z"), round("2026-11-14T09:00:00Z")] };
  await reload();
  const before = logReads;
  transport("open");
  await tick();
  assert(logReads > before, "Every stream open reloads the log, including the first open");
  health("Stream connected");
  health("Last recorded round 2h 00m ago");
  assert(document.querySelector("#mode [data-since]").title === "2026-11-14T10:00:00Z", "Round timestamp on hover");
  assert(!document.getElementById("mode").querySelector(".bg-emerald-500"), "No unconditional green indicator");
  transport("error");
  health("Stream disconnected");
  advance(60000);
  health("Last recorded round 2h 01m ago");
  for (const row of [round("2026-11-14T12:00:00Z", { backlog: "other" }),
    round("2026-11-14T12:00:00Z", { move: "rounds" }), round("2026-11-14T12:00:00Z", { move: "admit", task: "tl-1" }),
    round("invalid"), round("2026-02-30T12:00:00Z")]) logEvent(row);
  health("Last recorded round 2h 01m ago");
  logEvent(round("2026-11-14T12:00:00Z"));
  health("Last recorded round 1m 00s ago");
  advance(60000);
  health("Last recorded round 2m 00s ago");
  logSnapshot.rows = [round("2026-11-14T12:01:00Z")];
  transport("open");
  await tick();
  health("Stream connected");
  health("Last recorded round 1m 00s ago");
  send({ kind: "error", error: "fixture board failed" });
  health("Stream connected");
  assert(!document.getElementById("banner").hidden, "Application read errors retain the board failure banner");
  logSnapshot.rows = [round("2026-11-14T12:02:00Z", { backlog: "other" }), round("invalid")];
  boardError = new Error("fixture board failed");
  await reload();
  health("No round in available log");
  health("Stream connected");
  boardError = null;
  logSnapshot.rows = [round("2026-11-14T12:01:00Z")];
  await reload();
  health("Last recorded round 1m 00s ago");
  logResponse = () => { throw new Error("fixture log failed"); };
  await reload();
  health("Last round unavailable");
  logResponse = () => logSnapshot;
  logSnapshot.rows = [round("2026-11-14T12:03:00Z")];
  await reload();
  health("clock discrepancy");
  assert(!document.querySelector("#mode [data-since]"), "Future timestamp does not fabricate zero age");
  advance(120000);
  health("Last recorded round 1m 00s ago");
  logSnapshot.rows = [];
  await reload();
  health("No round in available log");
  assert(document.getElementById("banner").hidden, "Board recovers independently of an empty log");
}

async function healthRaces() {
  const old = deferred();
  logResponse = () => old.promise;
  send({ kind: "resync" });
  logEvent(round("2026-11-14T12:03:00Z"));
  old.resolve({ backlog, rows: [] });
  await tick();
  health("Last recorded round 1m 00s ago");
  const first = deferred();
  logResponse = () => first.promise;
  send({ kind: "resync" });
  logSnapshot.rows = [round("2026-11-14T12:04:00Z")];
  logResponse = () => logSnapshot;
  await reload();
  first.resolve({ backlog, rows: [round("2026-11-14T10:00:00Z")] });
  await tick();
  health("Last recorded round 0ms ago");
  const obsolete = deferred();
  logResponse = () => obsolete.promise;
  send({ kind: "resync" });
  logSnapshot.rows = [];
  logResponse = () => logSnapshot;
  await reload();
  obsolete.resolve({ backlog, rows: [round("2026-11-14T12:04:00Z")] });
  await tick();
  health("No round in available log");
  document.getElementById("nav-logs").click();
  await tick();
  logEvent(round("2026-11-14T12:04:00Z", { move: "rounds", words: ["stopped"] }));
  assert(document.getElementById("logs").textContent.includes("stopped"), "All log rows still reach the log screen");
  health("No round in available log");
  document.getElementById("nav-board").click();
}

try {
  await import("../../src/taskloop/dash/static/app.js");
  for (let n = 0; !stream && n < 100; n++) await tick();
  assert(stream, "App subscribed to stream");
  await liveDurations();
  health("Stream connecting");
  health("Last recorded round 2h 00m ago");
  for (const theme of ["light", "dark"]) {
    document.documentElement.className = theme;
    await healthStates();
    await healthRaces();
    await stoppedRounds();
    await stoppedRaces();
    await resync(mixed);
    for (const layout of ["view-columns", "view-lanes"]) {
      document.getElementById(layout).click();
      summary(2, 4);
      placement();
      questions();
      await drawers();
      await boardWords();
      await waitingStates();
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
    assert(!node("ask-new").textContent.includes("Needs you"), "Leaving Hold removes ask treatment");
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
  results.textContent = "PASS: stopped rounds, stream state and round age, reload races, owner attention and factory faults, "
    + "both layouts and themes";
} catch (error) {
  results.textContent = `FAIL: ${error.stack ?? error}`;
  throw error;
}
