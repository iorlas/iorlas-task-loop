// AskCard and LookCard: an open ask or look whole, never a one-liner (dash-spec §5.1), plus the "make it stick" row (§5.3).
// The card only lays out and calls back; the 5 s hold, the POSTs and the optimistic state live in actions.js.
import { html, useState } from '../../vendor/ui-runtime.js';
import * as act from '../actions.js';
import { causeOf, muted } from '../data.js';
import { age, bid } from '../format.js';
import { Md } from './kit.js';
import { draft, ui } from '../state.js';

export const CAUSES = { requirement: 'requirement gap', decision: 'decision', environment: 'environment', process: 'process',
  flaky_test: 'flaky test', wrong_plan: 'wrong plan', other: 'other', unknown: '? no cause' };
const ASK_CAUSES = ['requirement', 'decision', 'environment', 'process'];
export const ASK_BACK_CAP = 3;

export const STICKS = [
  ['adr', '📜', 'Record a decision', 'agents read it at plan'],
  ['factory', '🛠', 'Factory bead', 'fix the template, not this bead'],
  ['ref', '🔗', 'Already decided', 'link it to the decision in force'],
  ['fix', '✏️', 'Fix the bead text', 'plan runs again'],
  ['demote', '⬇', "Next time don't block", 'agent guesses, tells you at review'],
  ['once', '·', 'Just this once', 'nothing recorded'],
];

function CauseMark({ ask, onCause }) {
  const [edit, setEdit] = useState(false);
  if (edit) {
    return html`<span class="cause why">${ASK_CAUSES.map((c) => html`<button key=${c} class=${`fc ${ask.owner_cause === c ? 'on' : ''}`}
      onClick=${() => { setEdit(false); onCause(c); }}>${CAUSES[c]}</button>`)}</span>`;
  }
  return html`<button class="cause lnk" title="Correct the cause" onClick=${() => setEdit(true)}>
    cause (${ask.cause_by}): ${CAUSES[ask.owner_cause]} ✎</button>`;
}

export function Gallery({ shots, onOpen }) {
  if (!shots.length) return null;
  return html`<div class="gal">${shots.map((u, i) => html`<a key=${u} class=${i === 0 ? 'big' : ''} href=${u} target="_blank" rel="noopener"
    onClick=${onOpen ? (e) => { e.preventDefault(); onOpen(i); } : undefined}><img src=${u} alt=${`screen ${i + 1}`} loading="lazy" /></a>`)}</div>`;
}

// the "✓ Sent" line and the six optional outcomes; never blocks
export function StickRow({ ask, sent, onUndo, onStick }) {
  if (!sent) return null;
  return html`<div class="stick on"><div class="s1">✓ ${sent.held ? `Sending in ${sent.held}s` : 'Sent'}. ${bid(ask.bead, ask.project)} ${ask.blocking ? 'resumes in its slot' : 'keeps going'}.
      ${sent.held ? html` <button class="lnk" onClick=${onUndo}>Undo</button>` : html` <b>Make it stick?</b> optional, never blocks`}</div>
    ${!sent.held && html`<div class="bs">${STICKS.map(([k, i, t]) => html`<button key=${k} class=${sent.stick === k ? 'on' : ''}
      disabled=${!!sent.stick} onClick=${() => onStick(k)}>${i} ${t}</button>`)}</div>`}</div>`;
}

function AnswerBar({ ask, onAskBack, disabled }) {
  const k = `ask:${ask.id}`;
  const [text, setText] = useState(ui.drafts[k] || '');
  const send = () => { if (text.trim()) { onAskBack(text.trim(), k); setText(''); } };
  return html`<form class="askb" onSubmit=${(e) => { e.preventDefault(); send(); }}>
    <input value=${text} disabled=${disabled} placeholder="Ask back, or answer in your own words…" aria-label="Ask back or answer"
      onInput=${(e) => { setText(e.target.value); draft(k, e.target.value); }} />
    <button class="sb2" disabled=${disabled || !text.trim()}>Send</button></form>`;
}

// props: ask (AskCard), now, sent ({held, stick} once picked here), on{Pick,AskBack,Undo,Stick,Cause}
export function AskCard({ ask, now, sent, onPick, onAskBack, onUndo, onStick, onCause, head }) {
  const capped = ask.ask_backs >= ASK_BACK_CAP;
  return html`<div class="box you askcard">
    <div class="bh">${ask.blocking ? '🙋 Blocking · bead parked, slot freed' : `⏩ Not blocking · went on with ${ask.default || 'a default'}`}
      <${CauseMark} ask=${ask} onCause=${onCause} /></div>
    <div class="bb">${head}
      <p class="q">${ask.question}</p>
      ${(ask.why || ask.tried.length > 0) && html`<ul>${ask.why && html`<li>${ask.why}</li>`}${ask.tried.map((t, i) => html`<li key=${i}>${t}</li>`)}</ul>`}
      ${ask.stale > 0 && html`<p class="stale">⚠ ${ask.stale} bead${ask.stale > 1 ? 's' : ''} landed since this was asked</p>`}
      <${Gallery} shots=${ask.shots} />
      ${ask.options.map((o, i) => html`<button key=${i} class=${`op ${o.recommended ? 'rec' : ''} ${sent && sent.option === i ? 'chosen' : ''}`}
        disabled=${!!sent} onClick=${() => onPick(i)}>${o.recommended && html`<span class="r">${ask.blocking ? 'recommended' : 'running default'}</span>`}${o.label}<small>${o.consequence}</small></button>`)}
      ${ask.thread.length > 0 && html`<div class="thread">${ask.thread.map((m, i) => html`<div key=${i} class=${`tm ${m.by}`}>
        <div class="h">${m.by === 'owner' ? '💬 you' : m.by === 'helper' ? '📎 helper' : '🤖 agent'} · ${age(m.t, now)} ago</div><${Md} text=${m.md} /></div>`)}</div>`}
      ${capped ? html`<p class="cap3">${ASK_BACK_CAP} ask-backs: decide or defer.</p>` : html`<${AnswerBar} ask=${ask} onAskBack=${onAskBack} disabled=${!!sent} />`}
      ${ask.similar && html`<div class="sim">🔁 Similar: <b>${bid(ask.similar.bead, ask.project)}</b> asked “${ask.similar.question}” ${age(ask.similar.t, now)} ago → “${ask.similar.answer}”.</div>`}
      <${StickRow} ask=${ask} sent=${sent} onUndo=${onUndo} onStick=${onStick} />
    </div></div>`;
}

// a pending owner look: the gallery, ✅ Approve → land, ↩️ Send back (typed text required, never one tap)
export function LookCard({ ask, now, busy, onApprove, onSendBack, head }) {
  const [redo, setRedo] = useState(false);
  const k = `look:${ask.bead}`;
  const [text, setText] = useState(ui.drafts[k] || '');
  return html`<div class="box you askcard">
    <div class="bh">📸 Your look · ${ask.shots.length} screen${ask.shots.length === 1 ? '' : 's'}<span class="cause">${age(ask.t, now)} ago</span></div>
    <div class="bb">${head}<p class="q">${ask.question}</p><${Gallery} shots=${ask.shots} />
      <button class="op rec" disabled=${busy} onClick=${onApprove}>✅ Approve → land</button>
      ${redo ? html`<form class="askb" onSubmit=${(e) => { e.preventDefault(); if (text.trim()) onSendBack(text.trim(), k); }}>
          <input value=${text} placeholder="What is wrong? (required)" aria-label="Send back: what is wrong"
            onInput=${(e) => { setText(e.target.value); draft(k, e.target.value); }} />
          <button class="sb2" disabled=${busy || !text.trim()}>↩️ Send back</button></form>`
        : html`<button class="op" disabled=${busy} onClick=${() => setRedo(true)}>↩️ Send back (say why)</button>`}
    </div></div>`;
}

// the stop subset of the one cause list (§5.2), with "requirement gap" worded for a stop
const STOP_CAUSES = [['flaky_test', 'flaky test'], ['wrong_plan', 'wrong plan'], ['environment', 'environment'],
  ['requirement', 'requirement unclear'], ['other', 'other']];

// under a stuck or exited worker: why did it stop (one tap), ⏸ Park, 👁 Seen (§4, §6)
export function StopActions({ card }) {
  const c = causeOf(card), seen = muted(card);
  return html`<div class="stopa"><div class="k">Why did it stop?</div>
    <div class="chips">${STOP_CAUSES.map(([k, l]) => html`<button key=${k} class=${`fc ${c === k ? 'on' : ''}`}
      onClick=${() => act.cause(card.project, card.id, k)}>${l}</button>`)}</div>
    <div class="acts"><button onClick=${() => act.park(card.project, card.id)}>⏸ Park</button>
      <button class=${seen ? 'on' : ''} disabled=${seen} onClick=${() => act.ack(card.project, card.id)}>👁 ${seen ? 'Seen' : 'Seen, mute it'}</button></div></div>`;
}
