// Selectors over one snapshot: lookups, the client-side filters (dash-spec §11.2: filters apply on the client) and counts.
// Nothing here decides engine meaning; column, marker, status and tone come from the server.
import { ui } from './state.js';

const memo = new WeakMap();
// per-snapshot indexes, built once per snapshot object
export function idx(snap) {
  let m = memo.get(snap);
  if (!m) {
    m = { beads: new Map(), slots: new Map(), asks: new Map(), pieces: new Map(), lanes: new Map() };
    for (const b of snap.beads) m.beads.set(key(b.project, b.id), b);
    for (const s of snap.slots) m.slots.set(s.id, s);
    for (const a of snap.asks) m.asks.set(key(a.project, a.bead), a);
    for (const p of snap.pieces) {
      const k = key(p.project, p.bead);
      if (!m.pieces.has(k)) m.pieces.set(k, []);
      m.pieces.get(k).push(p);
    }
    for (const l of snap.lanes) m.lanes.set(l.id, l);
    memo.set(snap, m);
  }
  return m;
}

export const key = (project, id) => `${project}/${id}`;

// a bead by id, preferring the picked project: ids are unique per project, the deep link carries the id alone
export function bead(snap, id, project = ui.project) {
  if (!id) return null;
  const m = idx(snap);
  if (project !== 'all' && m.beads.has(key(project, id))) return m.beads.get(key(project, id));
  return snap.beads.find((b) => b.id === id) || null;
}

// the machine of a slot: Slot.machine when the server sends it, else the part of the slot name before "·"
export const machineOf = (slot) => (slot ? slot.machine || slot.id.split('·')[0] : '');
export const MACHINE_ICON = (m) => (/mac/i.test(m) ? '💻' : '🖥️');

export function machines(snap) {
  return [...new Set(snap.slots.map(machineOf))].filter(Boolean);
}

// answered here: held for its 5 s Undo, or sent
export const answered = (a) => !!ui.sent[a.id] || !!(ui.hold && ui.hold.ask.id === a.id);

// the open ask on a bead, unless answered here
export function askOf(snap, b) {
  const a = idx(snap).asks.get(key(b.project, b.id));
  return a && !answered(a) ? a : null;
}

export const allProjects = () => ui.project === 'all';

export function visible(snap, b) {
  if (ui.project !== 'all' && b.project !== ui.project) return false;
  if (ui.epic !== 'all' && b.epic !== ui.epic) return false;
  if (ui.machine !== 'all') {
    const s = b.slot ? idx(snap).slots.get(b.slot) : null;
    if (s && machineOf(s) !== ui.machine) return false;
  }
  return true;
}

// a bead answered here leaves Has questions / Your look at once (its card collapses out); the next snapshots place it
export function shown(snap) {
  const asks = idx(snap).asks;
  return snap.beads.filter((b) => visible(snap, b) && !((b.column === 'questions' || b.column === 'look')
    && asks.has(key(b.project, b.id)) && answered(asks.get(key(b.project, b.id)))));
}

export const epicsOf = (snap, project) => snap.epics.filter((e) => e.project === project);

export const troubleOf = (b) => b.marker === 'stuck' || b.marker === 'exited';
// the stop's cause: the server's, or the one picked here before the snapshot has it
export function causeOf(b) {
  const c = b.cause && b.cause !== 'unknown' ? b.cause : (ui.seen[key(b.project, b.id)] || {}).cause;
  return c || null;
}
// a stuck bead stays loud (red outline, Floor badge) until a cause is picked or 👁 Seen (§4)
export const muted = (b) => b.ack || !!causeOf(b) || !!(ui.seen[key(b.project, b.id)] || {}).ack;

export function counts(snap) {
  return {
    stuck: snap.beads.filter((b) => troubleOf(b) && !muted(b)).length,
    asks: snap.asks.filter((a) => !answered(a)).length,
  };
}

const LANE_ORDER = { locked: 0, watch: 1, stale: 2, ok: 3 };
export const lanesSorted = (snap) => [...snap.lanes].sort((a, b) => LANE_ORDER[a.state] - LANE_ORDER[b.state]);
// the top bar and the phone pill show only lanes that are not fine (dash-spec §8)
export const troubled = (snap) => lanesSorted(snap).filter((l) => l.state === 'watch' || l.state === 'locked');

export const piecesOf = (snap, b) => idx(snap).pieces.get(key(b.project, b.id)) || [];

export function filterLabel(snap) {
  const p = [];
  if (ui.project !== 'all') p.push(snap.projects.find((x) => x.id === ui.project)?.name || ui.project);
  if (ui.epic !== 'all') p.push(snap.epics.find((e) => e.id === ui.epic)?.title || ui.epic);
  if (ui.machine !== 'all') p.push(`${MACHINE_ICON(ui.machine)} ${ui.machine}`);
  return p;
}
