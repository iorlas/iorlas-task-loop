// UI state, kept apart from server data: the snapshot is replaced on every poll, this survives it and a reload.
// The deep link is #tab~option~bead~drawertab~goalpath (dash-spec §2.1). Filters, folds, drafts and the ledger filter persist
// per browser (localStorage); scroll positions persist per tab (sessionStorage). Each layer the phone's system back closes
// (sheet, bead page, goal level) is one history entry (§9).

const KEY = 'tl-dash-v2', SCROLL_KEY = 'tl-dash-v2-scroll';
const TABS = ['board', 'floor', 'decisions', 'lanes'];

function load(store, key) {
  try { return JSON.parse(store.getItem(key) || '{}'); } catch { return {}; }
}

function fromHash(h) {
  const [tab, opt, bead, dtab, gp] = decodeURIComponent(h.replace(/^#/, '')).split('~');
  return { tab: TABS.includes(tab) ? tab : 'board', opt: opt || '', bead: bead || null, dtab: dtab || '', gp: gp ? gp.split('/') : [] };
}

const saved = load(localStorage, KEY);
export const ui = {
  ...fromHash(location.hash),
  project: saved.project || 'all',
  epic: saved.epic || 'all',
  machine: saved.machine || 'all',
  folds: saved.folds || { backlog: true, done: true },
  drafts: saved.drafts || {},
  ledger: saved.ledger || 'all',
  wide: !!saved.wide,
  opts: saved.opts || {}, // the view option each tab had last (Board mode, Floor zoom, Decisions tab)
  sheet: null, // {kind, ...}: the phone's bottom sheet; also a history entry
  toast: null, // {text, n}: n changes so the same text shows again
  hold: null, // the 5 s answer hold (dash-api-v2 Undo): {key, req, label, until}
  sent: {}, // ask id -> {t, label, stick}: answered here; hidden until the snapshot drops it
  pruned: {}, // project/ADR id -> true: retired here, until the snapshot drops it
  outcomes: {}, // ask id -> outcome: made to stick from the Ledger, until the snapshot has it
  seen: {}, // project/bead -> {ack} or {cause}: optimistic Seen / cause until the snapshot says so
};

const subs = new Set();
export const subscribe = (fn) => (subs.add(fn), () => subs.delete(fn));
const emit = () => subs.forEach((fn) => fn());

export function hash() {
  const parts = [ui.tab, ui.opt, ui.bead || '', ui.dtab, ui.gp.join('/')];
  while (parts.length > 1 && !parts[parts.length - 1]) parts.pop();
  return '#' + parts.join('~');
}

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify({ project: ui.project, epic: ui.epic, machine: ui.machine, folds: ui.folds,
      drafts: ui.drafts, ledger: ui.ledger, wide: ui.wide, opts: { ...ui.opts, [ui.tab]: ui.opt } }));
  } catch { /* private mode: state lives for this page only */ }
}

// set(patch, {push}) updates state, persists the per-browser part, rewrites the hash and re-renders.
// push adds a history entry even when the hash stays (a sheet), so system back closes the top layer.
export function set(patch, opts = {}) {
  Object.assign(ui, patch);
  persist();
  const h = hash();
  if (opts.push) history.pushState({ sheet: ui.sheet }, '', h);
  else if (h !== location.hash) history.replaceState({ sheet: ui.sheet }, '', h);
  emit();
}

addEventListener('popstate', (e) => {
  Object.assign(ui, fromHash(location.hash), { sheet: (e.state && e.state.sheet) || null });
  emit();
});
addEventListener('hashchange', () => { Object.assign(ui, fromHash(location.hash)); emit(); });

// switch tab: each tab keeps its own view option; the bead page and goal level close
export const setTab = (tab) => set({ opts: { ...ui.opts, [ui.tab]: ui.opt }, tab, opt: ui.opts[tab] || '', bead: null, dtab: '', gp: [] });

export const fold = (k) => set({ folds: { ...ui.folds, [k]: !ui.folds[k] } });
export const draft = (k, v) => { ui.drafts = { ...ui.drafts, [k]: v }; persist(); };
export const clearDraft = (k) => { const d = { ...ui.drafts }; delete d[k]; ui.drafts = d; persist(); };
export const toast = (text) => set({ toast: { text, n: (ui.toast ? ui.toast.n : 0) + 1 } });
// close the top layer: a sheet, the bead page or a goal level, by going back in history when we pushed it
export const back = () => history.back();

// scroll positions by place (window per tab, the drawer body), restored once after the first render
const scrolls = load(sessionStorage, SCROLL_KEY);
let scrollTimer = 0;
export function rememberScroll(place, y) {
  scrolls[place] = Math.round(y);
  clearTimeout(scrollTimer);
  scrollTimer = setTimeout(() => { try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify(scrolls)); } catch { /* ignore */ } }, 150);
}
export const scrollOf = (place) => scrolls[place] || 0;
