// StageCard: one pass in the drawer, the 1k slot card living on (dash-spec §6): six phase cells over minutes and tokens,
// thumbnails under the phase that made them, the resumed note, the pass ending, then the messages of this pass.
import { html, useState } from '../../vendor/ui-runtime.js';
import { dur, tokens } from '../format.js';
import { MsgLine } from './kit.js';

export const PHASES = ['plan', 'write', 'test', 'review', 'look', 'land'];
export const END = { test_failed: '↩️', replan: '🔁', asked: '🙋', parked: '⏸️', lane_out: '⏸️', sent_back: '↩️', stuck: '🛑', exited: '💀', done: '✅' };
const NUM = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
export const passNum = (n) => NUM[n - 1] || `(${n})`;

const CELL = { done: 'v done', overrun: 'v overrun', visited: 'v done', small: 'v done', failed: 'v f', live: 'v act', you: 'v y', stuck: 'v x', skipped: 'k', empty: 'pending' };

// weight by size: under 20m and 300k recede, 20m+ or 300k+ stand out, 500k+ strongest; violet tint by absolute token bands
const weight = (c) => (c.tokens >= 500e3 ? 'w3' : c.secs >= 1200 || c.tokens >= 300e3 ? 'w2' : 'w1');
const band = (t) => (t >= 1e6 ? 't4' : t >= 500e3 ? 't3' : t >= 300e3 ? 't2' : t >= 150e3 ? 't1' : '');

function Cell({ c, onPick, selected }) {
  const pending = c.state === 'empty', skipped = c.state === 'skipped';
  const done = ['done', 'small', 'visited', 'overrun'].includes(c.state);
  const budget = c.budget_s != null ? `planned ${dur(c.budget_s)} · actual ${dur(c.secs)}` : '';
  const tip = `${c.phase} · ${pending ? 'not reached' : skipped ? 'skipped' : `${dur(c.secs)} · ${c.outcome || c.state} · ${tokens(c.tokens)}`}${budget ? ` · ${budget}` : ''}${c.last ? ` · ${c.last}` : ''}`;
  return html`<button data-stage=${c.phase} data-state=${c.state} aria-label=${tip} aria-expanded=${selected} class=${`${CELL[c.state]} ${weight(c)} ${done ? band(c.tokens) : ''}`} title=${tip} onClick=${() => onPick(c.phase)}>
    ${skipped ? '—' : !pending && html`<b>${done ? '✓ ' : c.state === 'failed' ? '✕ ' : ''}${dur(c.secs)}</b><span>${c.state === 'overrun' ? 'overrun' : c.outcome || c.state}</span>${budget && html`<span class="stage-budget">${budget}</span>`}`}</button>`;
}

function LogLine({ line }) {
  const [open, setOpen] = useState(false);
  return html`<button class=${`run-row ${open ? 'expanded' : ''}`} data-t=${line.t} title=${line.text}
    aria-expanded=${open} onClick=${() => setOpen(!open)}>${line.text}</button>`;
}

function StageLog({ log, phase }) {
  return html`<section class="stage-log" aria-label=${`${phase} log`}><h4>${phase} log</h4>
    ${!log?.roles.length ? html`<p>no log for this stage</p>` : log.roles.map((r) => html`<section key=${r.role} data-role=${r.role}>
      <h4>${r.role}</h4>${r.attempts.map((a, i) => {
        const lines = a.live ? [...a.lines].reverse().sort((x, y) => y.t - x.t).slice(0, 10) : a.lines;
        return html`<div key=${a.id} class="stage-attempt"><p>Attempt ${i + 1} · ${a.lane || '—'}${a.model && ` / ${a.model}`} · <time datetime=${new Date(a.t * 1000).toISOString()}>${new Date(a.t * 1000).toISOString()}</time> · ${dur(a.secs)} · ${a.outcome || '—'}</p>
          <div class=${`term ${a.live ? 'mini' : ''}`}>${lines.map((l, n) => html`<${LogLine} key=${n} line=${l} />`)}</div></div>`;
      })}</section>`)}</section>`;
}

// artifacts of this pass, under the phase that made them (or the running phase on the live pass)
function Thumbs({ pass, artifacts, livePhase }) {
  const mine = artifacts.filter((a) => a.kind === 'image' && a.pass_n === pass.n);
  if (!mine.length) return null;
  return html`<div class="row6 th">${PHASES.map((p) => {
    const here = mine.filter((a) => (a.phase || livePhase) === p);
    return html`<div key=${p}>${here.map((a) => html`<a key=${a.url} href=${a.url} target="_blank" rel="noopener"><img src=${a.url} alt=${a.name} loading="lazy" /></a>`)}</div>`;
  })}</div>`;
}

export function StageCard({ pass, now, artifacts = [], livePhase, live, children }) {
  const [selected, select] = useState(null);
  const pick = (phase) => select(selected === phase ? null : phase);
  return html`<div class="stagecard">
    <div class="row6 hd">${PHASES.map((p) => html`<button key=${p} class="e" onClick=${() => pick(p)} aria-expanded=${selected === p}>${p}</button>`)}</div>
    <div class="row6">${pass.cells.map((c) => html`<${Cell} key=${c.phase} c=${c} onPick=${pick} selected=${selected === c.phase} />`)}</div>
    <${Thumbs} pass=${pass} artifacts=${artifacts} livePhase=${livePhase} />
    ${selected && html`<${StageLog} phase=${selected} log=${pass.logs?.find((l) => l.phase === selected)} />`}
    ${pass.resumed && html`<div class="pend">↪ Resumed on <b>${pass.resumed.slot}</b> from branch <code>${pass.resumed.branch}</code> after ${dur(pass.resumed.waited_secs)} waiting for a slot</div>`}
    ${(pass.end || pass.end_text || pass.detail) && html`<div class="pend pass-why" title=${`${pass.end_text || pass.end.replace('_', ' ')}${pass.detail ? ` · ${pass.detail}` : ''}`}>
      ${END[pass.end] || ''} why: ${pass.end_text || pass.end.replace('_', ' ')}${pass.detail && ` · ${pass.detail}`}</div>`}
    ${live}${children}
    <div class="sx">Messages, newest first</div>
    <div class="stream">${pass.messages.map((m, i) => html`<div key=${i} data-phase-msg=${m.phase || ''} class=${i >= 10 ? 'old' : ''}><${MsgLine} msg=${m} now=${now} /></div>`)}
      ${!pass.messages.length && html`<div class="none">No messages in this pass.</div>`}</div>
  </div>`;
}
