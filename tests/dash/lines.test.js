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
