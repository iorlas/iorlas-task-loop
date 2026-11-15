import { apply, atBottom, lines, show } from "../../src/taskloop/dash/static/lines.js";

const assert = (condition, message) => { if (!condition) throw new Error(message); };
const event = (id, text) => ({ id, type: "message", text, at: "2026-11-15T10:00:00Z" });
const attempt = (state, feed) => ({ step: "implement", n: 1, state, feed, started_at: null });
const fixture = document.getElementById("fixture");

function mount(item) {
  const view = lines(item);
  view.style.height = "240px";
  view.style.width = "600px";
  fixture.replaceChildren(view);
  return view;
}

const message = (id) => document.querySelector(`#lines [data-eid="${id}"] .message-text`);
const disclosure = (id) => message(id).nextElementSibling;
const height = (node) => node.getBoundingClientRect().height;

function folded(id, count) {
  const node = message(id);
  const lineHeight = parseFloat(getComputedStyle(node).lineHeight);
  assert(height(node) > 0, `${id}: mounted message has height`);
  assert(Math.abs(height(node) - count * lineHeight) < 1, `${id}: shows ${count} rendered lines`);
  assert(disclosure(id).tagName === "BUTTON" && disclosure(id).type === "button", "native disclosure button");
  assert(disclosure(id).getAttribute("aria-expanded") === "false", `${id}: initially folded`);
}

export function messageFolding() {
  const rows = [
    event("short", "A short message"),
    event("eight", Array(8).fill("Line").join("\n")),
    event("nine", Array(9).fill("Line").join("\n")),
    event("space", "  indented\n\n    <b>literal text</b>"),
    event("wrapped", "A wrapped sentence. ".repeat(100)),
    event("word", "unbroken".repeat(200)),
  ];
  const item = attempt("succeeded", rows);
  mount(item);
  folded("short", 1);
  folded("eight", 8);
  folded("nine", 8);
  folded("space", 3);
  folded("wrapped", 8);
  folded("word", 8);
  for (const row of rows) {
    const node = message(row.id);
    assert(node.textContent === row.text, `${row.id}: complete original text retained`);
    assert(getComputedStyle(node).whiteSpace === "pre-wrap", "whitespace is preserved");
    assert(node.childElementCount === 0, "message markup remains literal text");
    disclosure(row.id).click();
    assert(disclosure(row.id).getAttribute("aria-expanded") === "true", "expansion state exposed");
    assert(disclosure(row.id).textContent === "Collapse message", "expanded button names its action");
    assert(node.clientHeight >= node.scrollHeight - 1, `${row.id}: expanded text is completely visible`);
  }
  assert(height(message("nine")) > 8 * parseFloat(getComputedStyle(message("nine")).lineHeight), "ninth line exposed");
  const expanded = message("nine");
  const arriving = event("arriving", Array(12).fill("New line").join("\n"));
  apply(item, arriving); show(item, arriving);
  folded("arriving", 8);
  assert(message("nine") === expanded && disclosure("nine").getAttribute("aria-expanded") === "true",
    "arrival preserves unrelated expanded rows");
  disclosure("arriving").click();
  assert(message("arriving").clientHeight >= message("arriving").scrollHeight - 1, "incremental message expands");
  disclosure("nine").click();
  folded("nine", 8);
}

const commandText = (id) => document.querySelector(`#lines [data-eid="${id}"] code`);
const commandButton = (id) => commandText(id).nextElementSibling;

function compactCommand(row) {
  const node = commandText(row.id);
  const button = commandButton(row.id);
  assert(node.textContent === row.cmd && node.childElementCount === 0, "complete command stays literal text");
  assert(getComputedStyle(node).whiteSpace === "nowrap", "compact command uses one line");
  assert(Math.abs(height(node) - parseFloat(getComputedStyle(node).lineHeight)) < 1, "preview has one rendered line");
  assert(button.tagName === "BUTTON" && button.type === "button" && button.tabIndex === 0, "native keyboard-operable button");
  assert(button.getAttribute("aria-expanded") === "false" && button.textContent === "Expand command", "compact action and state");
}

export function commandExpansion() {
  const text = `  printf '<b>literal</b>'\n\n    ${"long-token".repeat(180)}\n  last line  `;
  const rows = ["running", "finished", "unfinished"].map((state) => ({
    id: state, type: "command", cmd: text, state, at: "2026-11-15T10:00:00Z", duration_ms: 2000,
  }));
  rows.push({ ...rows[1], id: "failed", exit_code: 2 });
  rows.push({ ...rows[1], id: "short", cmd: "just test" });
  for (const state of ["running", "succeeded", "failed"]) {
    const item = attempt(state, [...rows]);
    mount(item);
    for (const row of rows) {
      compactCommand(row);
      const node = commandText(row.id);
      const button = commandButton(row.id);
      const status = node.closest(".event-row").lastElementChild;
      const timing = status.textContent;
      button.click();
      assert(button.getAttribute("aria-expanded") === "true" && button.textContent === "Collapse command", "expanded action and state");
      assert(node.textContent === row.cmd && node.childElementCount === 0, "expanded command preserves exact literal whitespace");
      assert(getComputedStyle(node).whiteSpace === "pre-wrap", "expanded whitespace is rendered");
      assert(node.clientHeight >= node.scrollHeight - 1 && node.clientWidth >= node.scrollWidth - 1,
        "full multiline command and long tokens fit the content column");
      assert(status.textContent === timing, "expansion preserves timing and status");
    }
    const expanded = commandText("finished");
    const arriving = { ...rows[1], id: "arriving" };
    apply(item, arriving); show(item, arriving);
    compactCommand(arriving);
    assert(commandText("finished") === expanded && commandButton("finished").getAttribute("aria-expanded") === "true",
      "arrival preserves unrelated expanded commands");
    const completed = { ...rows[0], state: "finished", exit_code: 3, cmd: text + "\nreplacement", duration_ms: 3000 };
    apply(item, completed); show(item, completed);
    compactCommand(completed);
    commandButton(completed.id).click();
    assert(commandText(completed.id).textContent === completed.cmd, "replacement expands to updated complete command");
    assert(commandText(completed.id).closest(".event-row").lastElementChild.textContent.includes("exit 3"), "replacement keeps failure");
    commandButton("finished").click();
    compactCommand(rows[1]);
    assert(commandText("unfinished").closest(".event-row").lastElementChild.textContent === "unfinished", "unfinished stays visible");
  }
}

export function toolRows() {
  const tool = { id: "tool", type: "tool", name: "Read", cmd: '"src/file with spaces.py"',
    state: "running", at: "2026-11-15T10:00:00Z" };
  const item = attempt("running", [tool]);
  mount(item);
  assert(commandText("tool").textContent === tool.cmd, "projected argument is displayed literally");
  assert(!commandButton("tool") && !commandText("tool").closest(".event-row").querySelector("button"), "tools have no command control");
  assert(commandText("tool").previousElementSibling.textContent === "Read", "tool name remains visible");
  assert(commandText("tool").closest(".event-row").lastElementChild.textContent.startsWith("running "), "tool running timing");
  const completed = { ...tool, state: "finished", duration_ms: 2000 };
  apply(item, completed); show(item, completed);
  assert(commandText("tool").textContent === tool.cmd, "replacement keeps relative argument");
  assert(commandText("tool").closest(".event-row").lastElementChild.textContent === "2s", "tool completed timing");
}

function newestVisible(box) {
  const row = document.getElementById("lines").lastElementChild;
  row.style.animation = "none";
  const bounds = box.getBoundingClientRect();
  const newest = row.getBoundingClientRect();
  assert(newest.top >= bounds.top && newest.bottom <= bounds.bottom + 1, "newest displayed event is visible");
  assert(atBottom(box), "jump resumes following at the bottom");
}

export function jumpToLatest() {
  for (const state of ["running", "succeeded", "failed"]) {
    const item = attempt(state, Array.from({ length: 18 }, (_, i) => event(`m${i}`, `Message ${i}\nSecond line`)));
    const view = mount(item);
    const box = view.querySelector("#tail");
    const jump = [...view.querySelectorAll("button")].find((button) => button.textContent === "Jump to latest");
    assert(jump?.type === "button" && !box.contains(jump), "jump is reachable outside the scrolling event content");
    assert(box.scrollHeight > box.clientHeight, `${state}: bounded fixture overflows`);
    box.scrollTop = 0;
    assert(!atBottom(box), "person starts at an earlier position");
    const arriving = event("new", "New displayed message");
    apply(item, arriving); show(item, arriving);
    assert(box.scrollTop === 0, "arrival preserves the earlier position before jumping");
    const control = jump.getBoundingClientRect();
    const bounds = view.getBoundingClientRect();
    assert(control.height > 0 && control.top >= bounds.top && control.bottom <= bounds.bottom, "jump stays visible");
    jump.click();
    newestVisible(box);
    if (state === "running") {
      const next = event("next", "Following the next live message");
      apply(item, next); show(item, next);
      newestVisible(box);
    }
  }
  const empty = mount(attempt("succeeded", []));
  empty.querySelector("button").click();
  assert(empty.querySelector("#lines").textContent.includes("No lines recorded"), "empty feed jump is harmless");
}
