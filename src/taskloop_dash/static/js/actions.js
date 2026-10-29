// Writes: every one a POST /api/v2/<verb> with its WRITES record (docs/contracts/dash-api-v2.md). An answer is held 5 s
// in the page before it is sent; that hold is the Undo (the server has none). What was answered here stays answered in the
// page until the snapshot drops the ask, so a card never flickers back between polls.
import * as api from './api.js';
import { bid } from './format.js';
import { clearDraft, set, toast, ui } from './state.js';

export const HOLD_MS = 5000;
const SENT_KEEP_S = 600; // a sent ask the snapshot still lists after this is shown again: the server did not take it

let holdTimer = 0;

function sentPatch(id, v) {
  const sent = { ...ui.sent };
  if (v) sent[id] = v; else delete sent[id];
  return sent;
}

async function flush() {
  clearTimeout(holdTimer);
  const h = ui.hold;
  if (!h) return;
  set({ hold: null, sent: sentPatch(h.ask.id, { ask: h.ask, option: h.option, label: h.label, t: Date.now() / 1000, stick: null }) });
  const res = await api.write('answer', h.req);
  if (!res.ok) {
    set({ sent: sentPatch(h.ask.id, null) });
    toast(`⚠️ ${res.message || 'the answer was refused'}`);
  } else if (h.draft) {
    clearDraft(h.draft);
  }
}

// hold an answer for 5 s (Undo), then POST it; a second answer flushes the first at once
export function answer(ask, option, text = '', draftKey = '', opts = {}) {
  if (ui.hold) flush();
  const label = option != null ? ask.options[option].label : text;
  const req = { project: ask.project, ask: ask.id, kind: 'answer', option, text };
  set({ hold: { ask, option, label, req, draft: draftKey, until: Date.now() + HOLD_MS } }, opts);
  holdTimer = setTimeout(flush, HOLD_MS);
}

export function undo() {
  clearTimeout(holdTimer);
  set({ hold: null });
  toast('Undone · nothing was sent');
}

// free text that asks a question is an ask back (💬) and keeps the ask open; any other text is an answer, held like one
export async function reply(ask, text, draftKey) {
  if (!/\?\s*$/.test(text)) return answer(ask, null, text, draftKey);
  const res = await api.write('answer', { project: ask.project, ask: ask.id, kind: 'ask_back', option: null, text });
  if (res.ok) { clearDraft(draftKey); toast('💬 Asked back · the answer comes into this card'); } else toast(`⚠️ ${res.message}`);
  return res;
}

export async function stick(askId, outcome, text = '') {
  const s = ui.sent[askId];
  if (!s) return;
  set({ sent: sentPatch(askId, { ...s, stick: outcome }) });
  const res = await api.write('stick', { project: s.ask.project, ask: askId, outcome, text });
  if (!res.ok) { set({ sent: sentPatch(askId, { ...s, stick: null }) }); toast(`⚠️ ${res.message}`); } else if (res.message) toast(res.message);
}

// retire a decision in force: it leaves the list at once and comes back on a refusal
export async function pruneAdr(project, adr) {
  const k = `${project}/${adr}`;
  set({ pruned: { ...ui.pruned, [k]: true } });
  const res = await api.write('prune', { project, adr });
  if (!res.ok) {
    const p = { ...ui.pruned };
    delete p[k];
    set({ pruned: p });
    toast(`⚠️ ${res.message}`);
  } else toast(`🗑 ${adr} retired · plans stop reading it`);
  return res;
}

export const dismiss = (askId) => set({ sent: sentPatch(askId, null) });

// make it stick later, from a Ledger row: no hold, the row shows the outcome at once and takes it back on a refusal
export async function stickRow(row, outcome) {
  set({ outcomes: { ...ui.outcomes, [row.ask]: outcome } });
  const res = await api.write('stick', { project: row.project, ask: row.ask, outcome, text: '' });
  if (!res.ok) {
    const o = { ...ui.outcomes };
    delete o[row.ask];
    set({ outcomes: o });
    toast(`⚠️ ${res.message}`);
  } else if (res.message) toast(res.message);
  return res;
}

const seenPatch = (k, v) => { const seen = { ...ui.seen }; if (v) seen[k] = v; else delete seen[k]; return seen; };

// a cause on an ask, or on a stop; a stop's cause also mutes its red outline (§4), shown at once until the snapshot has it
export async function cause(project, bead, value, askId = null) {
  const k = `${project}/${bead}`;
  if (!askId) set({ seen: seenPatch(k, { cause: value }) });
  const res = await api.write('cause', { project, bead, cause: value, ask: askId });
  if (!res.ok && !askId) set({ seen: seenPatch(k, null) });
  toast(res.ok ? `Cause set: ${value.replace('_', ' ')}` : `⚠️ ${res.message}`);
  return res;
}

// 👁 Seen: the stuck outline fades and the Floor badge stops counting it until something changes
export async function ack(project, bead) {
  const k = `${project}/${bead}`;
  set({ seen: seenPatch(k, { ack: true }) });
  const res = await api.write('ack', { project, bead, ack: true });
  if (!res.ok) { set({ seen: seenPatch(k, null) }); toast(`⚠️ ${res.message}`); }
  return res;
}

// ⏹ Stop: the run ends now, the branch is kept (the page confirms first)
export async function stop(project, bead) {
  const res = await api.write('stop', { project, bead });
  toast(res.ok ? `⏹ ${bead} stopped · branch kept` : `⚠️ ${res.message}`);
  return res;
}

// ✉️ a note for the worker, or a comment on a done bead: a bead comment every later stage reads
export async function note(project, bead, text, draftKey) {
  const res = await api.write('note', { project, bead, text });
  if (res.ok) clearDraft(draftKey);
  toast(res.ok ? `✉️ Saved on ${bead} · its next stage reads it` : `⚠️ ${res.message}`);
  return res;
}

export async function park(project, bead) {
  const res = await api.write('park', { project, bead });
  toast(res.ok ? `⏸ Parked · ${bead} frees its slot` : `⚠️ ${res.message}`);
  return res;
}

// a look: approve lands it; a send back needs the reason in words
export async function look(ask, verdict, note = '', draftKey = '') {
  set({ sent: sentPatch(ask.id, { ask, look: verdict, t: Date.now() / 1000 }) });
  const res = await api.write('look', { project: ask.project, bead: ask.bead, verdict, note });
  if (!res.ok) { set({ sent: sentPatch(ask.id, null) }); toast(`⚠️ ${res.message}`); return res; }
  if (draftKey) clearDraft(draftKey);
  toast(verdict === 'good' ? `✅ Approved · ${bid(ask.bead, ask.project)} is landing` : `↩️ Sent back · ${bid(ask.bead, ask.project)} goes back to write`);
  return res;
}

// forget what was sent here after a while: the snapshot has dropped the ask by then, or the server did not take it and
// the card shows again
export function prune() {
  const now = Date.now() / 1000;
  const stale = Object.keys(ui.sent).filter((id) => now - ui.sent[id].t > SENT_KEEP_S);
  if (stale.length) ui.sent = Object.fromEntries(Object.entries(ui.sent).filter(([id]) => !stale.includes(id)));
}

// the AskCard / LookCard callbacks for one ask (drawer, Decisions › Waiting)
export function hooks(ask) {
  const held = ui.hold && ui.hold.ask.id === ask.id ? ui.hold : null;
  const s = ui.sent[ask.id];
  const state = held ? { held: Math.max(1, Math.ceil((held.until - Date.now()) / 1000)), option: held.option }
    : s ? { held: 0, option: s.option, stick: s.stick } : null;
  return {
    ask: { sent: state, onPick: (i) => answer(ask, i), onAskBack: (t, k) => reply(ask, t, k), onUndo: undo,
      onStick: (o) => stick(ask.id, o), onCause: (c) => cause(ask.project, ask.bead, c, ask.id) },
    look: { busy: !!s, onApprove: () => look(ask, 'good'), onSendBack: (t, k) => look(ask, 'redo', t, k) },
  };
}
