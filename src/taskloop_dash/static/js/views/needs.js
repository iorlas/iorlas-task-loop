// The needs-you list and the loop-health strip (tl-9un.2): everything that waits on the owner with no ask to answer, oldest first,
// shown first on the phone's Board. The server builds the rows from records the engine already writes (views/needs.py); the page
// only lays them out. A bead row opens its bead page; a row with no bead (a slot, a lane, a loop) is text.
import { html } from '../../vendor/ui-runtime.js';
import { bead as findBead } from '../data.js';
import { age, bid, clock } from '../format.js';
import { openBead } from './shell.js';

const ICON = { label: '✋', block: '⏳', parked: '⏸️', capped: '🧢', paused: '💤', slot_held: '🔒', slot_aside: '🔒', slot_setup: '🛠️', stray: '👻', stalled: '🐌', absent: '🕳️' };
const HEALTH = { ok: ['ok', 'running'], stalled: ['w', 'stalled'], absent: ['x', 'no loop'] };

export function LoopStrip({ snap, now }) {
  return html`<div class="hs">${snap.server.loops.map((l) => {
    const [tone, word] = l.health === 'ok' && !l.running ? ['', 'idle'] : HEALTH[l.health];
    return html`<span key=${l.project} class="hsi"><i class=${`dt ${tone}`}></i>${l.project} · ${word}${l.ready ? ` · ${l.ready} ready` : ''}${l.health !== 'ok' && l.quiet_since ? ` · quiet ${age(l.quiet_since, now)}` : ''}</span>`;
  })}</div>`;
}

function Row({ snap, n, now }) {
  const b = n.bead && findBead(snap, n.bead, n.project);
  const who = n.bead ? bid(n.bead, n.project, snap.projects.length > 1) : '';
  const body = html`<i class="ni">${ICON[n.kind] || '•'}</i><span class="nt"><b>${who}${b ? ` ${b.title}` : n.title && !who ? n.title : ''}</b>
    <span>${n.why}</span></span><span class="nw">${n.since != null ? `${age(n.since, now)} ago` : ''}${n.until != null ? `${n.since != null ? ' · ' : ''}until ${clock(n.until)}` : ''}</span>`;
  return b ? html`<button class="nr" onClick=${() => openBead(b)}>${body}</button>` : html`<div class="nr">${body}</div>`;
}

export function Needs({ snap, now }) {
  return html`<section class="needs"><${LoopStrip} snap=${snap} now=${now} />
    ${snap.needs.length > 0 && html`<div class="nh">Needs you · ${snap.needs.length}</div>
    <div class="nl">${snap.needs.map((n, i) => html`<${Row} key=${i} snap=${snap} n=${n} now=${now} />`)}</div>`}</section>`;
}
