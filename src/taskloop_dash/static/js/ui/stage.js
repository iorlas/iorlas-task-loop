// StageCard: one pass in the drawer, the 1k slot card living on (dash-spec §6): six phase cells over minutes and tokens,
// thumbnails under the phase that made them, the resumed note, the pass ending, then the messages of this pass.
import { html } from '../../vendor/ui-runtime.js';
import { dur, tokens } from '../format.js';
import { MsgLine } from './kit.js';

export const PHASES = ['plan', 'write', 'test', 'review', 'look', 'land'];
export const END = { test_failed: '↩️', replan: '🔁', asked: '🙋', parked: '⏸️', lane_out: '⏸️', sent_back: '↩️', stuck: '🛑', exited: '💀', done: '✅' };
const NUM = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
export const passNum = (n) => NUM[n - 1] || `(${n})`;

const CELL = { visited: 'v', small: 'v s', failed: 'v f', live: 'v act', you: 'v y', stuck: 'v x', skipped: 'k', empty: '' };

// weight by size: under 20m and 300k recede, 20m+ or 300k+ stand out, 500k+ strongest; violet tint by absolute token bands
const weight = (c) => (c.tokens >= 500e3 ? 'w3' : c.secs >= 1200 || c.tokens >= 300e3 ? 'w2' : 'w1');
const band = (t) => (t >= 1e6 ? 't4' : t >= 500e3 ? 't3' : t >= 300e3 ? 't2' : t >= 150e3 ? 't1' : '');

function Cell({ c, onPick }) {
  const tip = `${c.phase} · ${dur(c.secs)} · ${tokens(c.tokens)}${c.last ? ` · ${c.last}` : ''}`;
  if (c.state === 'skipped') return html`<div class="k" title=${`${c.phase} skipped`}>—</div>`;
  if (c.state === 'empty') return html`<div title=${`${c.phase} not reached`}></div>`;
  return html`<button class=${`${CELL[c.state]} ${c.state === 'small' ? '' : `${weight(c)} ${band(c.tokens)}`}`} title=${tip} onClick=${() => onPick(c.phase)}>
    ${c.state !== 'small' && html`<b>${dur(c.secs)}</b><span class="k">${tokens(c.tokens)}</span>`}</button>`;
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
  const pick = (phase) => {
    const el = document.querySelector(`[data-phase-msg="${phase}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  return html`<div class="stagecard">
    <div class="row6 hd">${PHASES.map((p) => html`<div key=${p} class="e">${p}</div>`)}</div>
    <div class="row6">${pass.cells.map((c) => html`<${Cell} key=${c.phase} c=${c} onPick=${pick} />`)}</div>
    <${Thumbs} pass=${pass} artifacts=${artifacts} livePhase=${livePhase} />
    ${pass.resumed && html`<div class="pend">↪ Resumed on <b>${pass.resumed.slot}</b> from branch <code>${pass.resumed.branch}</code> after ${dur(pass.resumed.waited_secs)} waiting for a slot</div>`}
    ${pass.end && html`<div class="pend">${END[pass.end] || ''} ${pass.end_text || pass.end.replace('_', ' ')}</div>`}
    ${live}${children}
    <div class="sx">Messages, newest first</div>
    <div class="stream">${pass.messages.map((m, i) => html`<div key=${i} data-phase-msg=${m.phase || ''} class=${i >= 10 ? 'old' : ''}><${MsgLine} msg=${m} now=${now} /></div>`)}
      ${!pass.messages.length && html`<div class="none">No messages in this pass.</div>`}</div>
  </div>`;
}
