// The bead page's bottom controls (dash-spec §6, §9): ⏸ Park · ⏹ Stop (confirmed, never one tap) · ✉️ Note for the worker.
// A done bead shows Comment only. On the phone the bar holds buttons and Stop and Note open bottom sheets; a look shows
// ✅ Approve → land · Note instead.
import { html, useState } from '../../vendor/ui-runtime.js';
import * as act from '../actions.js';
import { askOf } from '../data.js';
import { bid } from '../format.js';
import { back, draft, set, ui } from '../state.js';

const active = (c) => c.column !== 'done' && c.column !== 'backlog';
const noteKey = (c) => `note:${c.project}/${c.id}`;
const noteHint = (c) => (c.column === 'done' ? '💬 Comment on the bead' : '✉️ Note for the worker · read when its next stage starts');

function NoteForm({ card, rows, onSent, cancel }) {
  const k = noteKey(card);
  const [text, setText] = useState(ui.drafts[k] || '');
  const send = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    const res = await act.note(card.project, card.id, text.trim(), k);
    if (res.ok) { setText(''); if (onSent) onSent(); }
  };
  const input = { value: text, placeholder: noteHint(card), 'aria-label': noteHint(card), onInput: (e) => { setText(e.target.value); draft(k, e.target.value); } };
  return html`<form class=${rows ? 'notef' : 'note1'} onSubmit=${send}>
    ${rows ? html`<textarea rows=${rows} ...${input}></textarea>` : html`<input ...${input} />`}
    ${rows ? html`<div class="row2">${cancel}<button class="pri" disabled=${!text.trim()}>Send</button></div>` : html`<button class="pri" disabled=${!text.trim()}>Send</button>`}</form>`;
}

export function Controls({ card }) {
  const [confirm, setConfirm] = useState(false);
  if (confirm) {
    return html`<div class="ctl cf"><span>Stop ${bid(card.id, card.project)}? The run ends now; branch <code>bd/${card.id}</code> is kept.</span>
      <button class="stop on" onClick=${() => { setConfirm(false); act.stop(card.project, card.id); }}>⏹ Stop the run</button>
      <button onClick=${() => setConfirm(false)}>Cancel</button></div>`;
  }
  return html`<div class="ctl">${active(card) && html`<button title="parks at the next safe point; the slot takes other work"
      onClick=${() => act.park(card.project, card.id)}>⏸ Park</button><button class="stop" onClick=${() => setConfirm(true)}>⏹ Stop</button>`}
    <${NoteForm} card=${card} /></div>`;
}

const sheet = (kind, card) => set({ sheet: { kind, project: card.project, bead: card.id } }, { push: true });

export function PhoneControls({ snap, card }) {
  const ask = askOf(snap, card);
  if (ask && ask.source === 'look') {
    return html`<div class="pab"><button class="pri" onClick=${() => act.look(ask, 'good')}>✅ Approve → land</button>
      <button onClick=${() => sheet('note', card)}>✉️ Note</button></div>`;
  }
  if (!active(card)) return html`<div class="pab"><button onClick=${() => sheet('note', card)}>${card.column === 'done' ? '💬 Comment' : '✉️ Note'}</button></div>`;
  return html`<div class="pab"><button onClick=${() => act.park(card.project, card.id)}>⏸ Park</button>
    <button class="stop" onClick=${() => sheet('stop', card)}>⏹ Stop</button><button onClick=${() => sheet('note', card)}>✉️ Note</button></div>`;
}

const cardOf = (snap, arg) => snap.beads.find((b) => b.project === arg.project && b.id === arg.bead);

export function StopSheet({ snap, arg }) {
  const card = cardOf(snap, arg);
  if (!card) return html`<p>${arg.bead} is gone from the board.</p><button class="wide" onClick=${back}>Close</button>`;
  return html`<h3>Stop ${bid(card.id, card.project)}?</h3><p>The run ends now. Branch <code>bd/${card.id}</code> is kept.</p>
    <button class="wide danger" onClick=${() => { act.stop(card.project, card.id); back(); }}>⏹ Stop the run</button>
    <button class="wide" onClick=${back}>Cancel</button>`;
}

export function NoteSheet({ snap, arg }) {
  const card = cardOf(snap, arg);
  if (!card) return html`<p>${arg.bead} is gone from the board.</p><button class="wide" onClick=${back}>Close</button>`;
  return html`<h3>${card.column === 'done' ? 'Comment' : 'Note for the worker'}</h3>
    <p>${card.column === 'done' ? `Saved as a comment on ${card.id}.` : `${card.id} reads it when its next stage starts.`}</p>
    <${NoteForm} card=${card} rows=${4} onSent=${back} cancel=${html`<button type="button" onClick=${back}>Cancel</button>`} />`;
}
