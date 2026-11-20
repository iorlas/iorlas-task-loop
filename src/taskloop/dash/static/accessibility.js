// DOM-only keyboard, tab and modal focus behaviour shared by the board and drawer.
import { el } from "./ui.js";

const controls = 'button, [href], input, select, textarea, summary, [tabindex]';
let invoker = null;
let background = [];

export function activateCard(node, activate) {
  node.setAttribute("role", "button");
  node.tabIndex = 0;
  const nested = (target) => target !== node
    && target.closest(`${controls}, [role="button"], [contenteditable="true"]`) !== node;
  node.addEventListener("click", (event) => { if (!nested(event.target)) activate(); });
  node.addEventListener("keydown", (event) => {
    if (nested(event.target) || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    if (!event.repeat) activate();
  });
}

export function tabState(button, selected) {
  button.setAttribute("aria-selected", String(selected));
  button.tabIndex = selected ? 0 : -1;
}

export function initTabList(bar) {
  if (!bar) return;
  bar.setAttribute("role", "tablist");
  bar.addEventListener("keydown", (event) => {
    const tabs = [...bar.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(event.target);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    const id = tabs[next].id;
    tabs[next].click();
    document.getElementById(id)?.focus(); // selection may have rebuilt the bar
  });
}

export function tabBar(group, label, items, selected, choose) {
  const bar = el("div", "mt-3 flex min-w-0 flex-wrap gap-x-5 gap-y-2 border-b border-slate-200 px-6 dark:border-slate-800");
  bar.setAttribute("aria-label", label);
  for (const [id, text] of items) {
    const on = id === selected;
    const button = el("button", "-mb-px border-b-2 pb-2 text-sm " + (on
      ? "border-slate-900 font-semibold dark:border-slate-100"
      : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"), text);
    button.type = "button";
    button.id = `${group}-tab-${id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", `${group}-panel-${id}`);
    tabState(button, on);
    button.addEventListener("click", () => choose(id));
    bar.append(button);
  }
  initTabList(bar);
  const fragment = document.createDocumentFragment();
  fragment.append(bar);
  for (const [id] of items) {
    if (id === selected) continue;
    const panel = tabPanel(el("div"), group, id);
    panel.hidden = true;
    fragment.append(panel);
  }
  return fragment;
}

export function tabPanel(node, group, selected) {
  if (node.id) {
    const wrap = el("div", "flex min-h-0 min-w-0 flex-1 flex-col");
    wrap.append(node); // preserve content IDs used by scrolling and live updates
    node = wrap;
  }
  node.id = `${group}-panel-${selected}`;
  node.setAttribute("role", "tabpanel");
  node.setAttribute("aria-labelledby", `${group}-tab-${selected}`);
  node.tabIndex = 0;
  return node;
}

const available = (node) => !node.disabled && !node.closest('[hidden], [inert], [aria-hidden="true"]')
  && node.getClientRects().length > 0;
const focusable = (drawer) => [...drawer.querySelectorAll(controls)].filter((node) => node.tabIndex >= 0 && available(node));

export function closeButton(close) {
  const button = el("button", "rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 "
    + "hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800", "Close");
  button.id = "drawer-close";
  button.type = "button";
  button.addEventListener("click", close);
  return button;
}

export function initDialog(drawer, close) {
  drawer.tabIndex = -1;
  drawer.onkeydown = (event) => {
    if (event.key === "Escape") { event.preventDefault(); close(); }
    if (event.key !== "Tab") return;
    const nodes = focusable(drawer);
    const index = nodes.indexOf(document.activeElement);
    if (!nodes.length || index < 0 || (!event.shiftKey && index === nodes.length - 1) || (event.shiftKey && index === 0)) {
      event.preventDefault();
      (event.shiftKey ? nodes.at(-1) ?? drawer : nodes[0] ?? drawer).focus();
    }
  };
}

export function openDialog(drawer) {
  if (!drawer.inert && drawer.getAttribute("aria-hidden") === "false") return;
  invoker = document.activeElement;
  background = [...document.body.children]
    .filter((node) => node !== drawer && !node.contains(drawer) && node.id !== "backdrop")
    .map((node) => [node, node.inert]);
  background.forEach(([node]) => { node.inert = true; });
  drawer.inert = false;
  drawer.setAttribute("aria-hidden", "false");
  drawer.focus();
}

export function closeDialog(drawer) {
  drawer.inert = true;
  drawer.setAttribute("aria-hidden", "true");
  background.forEach(([node, inert]) => { node.inert = inert; });
  background = [];
  const fallback = document.querySelector('#screens [aria-selected="true"]') ?? document.getElementById("nav-board");
  (invoker?.isConnected && available(invoker) ? invoker : fallback)?.focus();
  invoker = null;
}

const focusKey = (node) => node.id || [node.tagName, node.getAttribute("aria-label") ?? node.textContent,
  node.closest("[data-run]")?.dataset.run ?? ""].join("|");

export function preserveDialogFocus(drawer, update) {
  const active = document.activeElement;
  const key = drawer.contains(active) ? focusKey(active) : null;
  update();
  if (key && !drawer.inert && drawer.getAttribute("aria-hidden") === "false") {
    const replacement = [...drawer.querySelectorAll(controls)].find((node) => focusKey(node) === key && available(node));
    (replacement ?? drawer).focus({ preventScroll: true });
  }
}
