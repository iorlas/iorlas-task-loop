// Board › Flow: columns derived by the server (BeadCard.column), never dragged (dash-spec §3); phone sections per §9.
import { html } from '../../vendor/ui-runtime.js';
import { allProjects, shown } from '../data.js';
import { age, bid } from '../format.js';
import { fold, ui } from '../state.js';
import { BeadCard, Dots, Nothing, Status } from '../ui/kit.js';

const COLS = [
  ['backlog', 'Backlog'], ['working', 'Working'], ['questions', 'Has questions'], ['review', 'AI review'],
  ['look', 'Your look'], ['landing', 'Landing'], ['done', 'Done'],
];
const BACKLOG_SHOWN = 5; // (default)

export function Flow({ snap, now, onOpen }) {
  const beads = shown(snap), all = allProjects();
  return html`<div class="board">
    ${COLS.map(([k, name]) => {
      const list = beads.filter((b) => b.column === k);
      const you = k === 'questions' || k === 'look';
      const items = k === 'backlog' ? list.slice(0, BACKLOG_SHOWN) : list;
      const more = list.length - items.length + (k === 'backlog' ? snap.backlog_more : 0);
      return html`<div key=${k} class=${`col ${k} ${you ? 'you' : ''}`}><h4>${name}<span class="c">${list.length + (k === 'backlog' ? snap.backlog_more : 0)}</span></h4>
        ${k === 'done'
          ? list.map((b) => html`<button key=${b.project + b.id} class="dn" onClick=${() => onOpen(b)}>✅ ${b.title}</button>`)
          : items.map((b) => html`<${BeadCard} key=${b.project + b.id} card=${b} all=${all} now=${now} why=${k === 'backlog'}
              sel=${ui.bead === b.id} onOpen=${onOpen} />`)}
        ${!list.length && html`<${Nothing} />`}
        ${more > 0 && html`<div class="more">+${more} more</div>`}
      </div>`;
    })}</div>`;
}

const SECTIONS = [
  ['stuck', '🛑 Stuck', (b) => b.marker === 'stuck' || b.marker === 'exited', 'bad'],
  ['you', '🙋 Needs you', (b) => b.column === 'questions' || b.column === 'look', 'you'],
  ['working', '▶ Working', (b) => b.column === 'working' && b.marker !== 'stuck' && b.marker !== 'exited', ''],
  ['review', '👀 AI review', (b) => b.column === 'review', ''],
  ['landing', '🚀 Landing', (b) => b.column === 'landing', ''],
  ['backlog', '▷ Backlog', (b) => b.column === 'backlog', ''],
  ['done', '✅ Done today', (b) => b.column === 'done', ''],
];
const HIDE_EMPTY = new Set(['stuck', 'landing']);
const PHONE_BACKLOG = 20;
const PC_TONE = { stuck: 'stuck', exited: 'stuck', ask: 'ask', look: 'you', soft_ask: 'you', run: 'run' };

export function PhoneCard({ b, all, now, onOpen, actions }) {
  const meta = [bid(b.id, b.project, all), b.column !== 'done' && b.column !== 'backlog' && b.slot, age(b.t, now)].filter(Boolean).join(' · ');
  return html`<article class=${`pc ${PC_TONE[b.marker] || ''}`} onClick=${() => onOpen(b)}>
    <div class="t">${b.goal ? '🎯 ' : ''}${b.title}</div><div class="s"><${Status} card=${b} /></div>
    ${b.column === 'backlog' && b.waits_why && html`<div class="s ww">${b.waits_why}</div>`}
    <div class="mt"><span>${meta}</span><${Dots} dots=${b.dots} loops=${b.loops} /></div>${actions && actions(b)}</article>`;
}

// actions(b) adds the quick actions of §9 under a card (phone.js passes them)
export function PhoneFlow({ snap, now, onOpen, actions }) {
  const beads = shown(snap), all = allProjects();
  return SECTIONS.map(([k, name, fn, tone]) => {
    const all2 = beads.filter(fn);
    if (!all2.length && HIDE_EMPTY.has(k)) return null;
    const folded = !!ui.folds[k];
    const list = k === 'backlog' ? all2.slice(0, PHONE_BACKLOG) : all2;
    const more = all2.length - list.length + (k === 'backlog' ? snap.backlog_more : 0);
    return html`<section key=${k} class=${`ps ${tone}`}><h3><button class="fold" aria-expanded=${!folded} onClick=${() => fold(k)}>${name}<span class="c">${all2.length + (k === 'backlog' ? snap.backlog_more : 0)}</span>
        <span class=${`chev ${folded ? '' : 'o'}`}>›</span></button></h3>
      ${!folded && (k === 'done'
        ? html`<div class="pl">${list.map((b) => html`<div key=${b.project + b.id} class="gr done" onClick=${() => onOpen(b)}><span class="e">✅</span>
            <div><div class="t">${b.title}</div><div class="s">${bid(b.id, b.project, all)} · ${age(b.t, now)} ago</div></div></div>`)}
            ${!list.length && html`<p class="emp">Nothing here.</p>`}</div>`
        : html`<div class="cl">${list.map((b) => html`<${PhoneCard} key=${b.project + b.id} b=${b} all=${all} now=${now} onOpen=${onOpen} actions=${actions} />`)}
            ${!list.length && html`<p class="emp">Nothing here.</p>`}${more > 0 && html`<p class="emp">+${more} more in the backlog</p>`}</div>`)}
    </section>`;
  });
}
