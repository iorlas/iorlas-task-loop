// The phone shell below 600 px (dash-spec §9): its own layout over the same data and renderers, not a squeeze of the desktop.
// Header with the lanes-in-trouble pill, a bottom tab bar, the bead page pushed from the right, bottom sheets. System back
// closes the top layer: sheet → bead page → goal level (each is a history entry).
import { html, useEffect, useRef } from '../../vendor/ui-runtime.js';
import * as act from '../actions.js';
import { askOf, counts, filterLabel, shown, troubled, bead as findBead } from '../data.js';
import { bid, pct } from '../format.js';
import { back, set, ui, setTab } from '../state.js';
import { STICKS } from '../ui/ask.js';
import { FilterChips, Sheet } from '../ui/kit.js';
import { PhoneFlow } from './board.js';
import { NoteSheet, StopSheet } from './controls.js';
import { Decisions } from './decisions.js';
import { Needs } from './needs.js';
import { PhoneGoals } from './goals.js';
import { PhoneLanes } from './lanes.js';
import { PhoneFloor } from './floor.js';
import { BeadPage } from './drawer.js';
import { Banners, epicProject, filterGroups, openBead, TABS } from './shell.js';

function LanePill({ snap }) {
  const lanes = troubled(snap);
  if (!lanes.length) return null;
  return html`<button class="lp" onClick=${() => setTab('lanes')}>${lanes.map((l) => html`<span key=${l.id} class="lpi">
    <i class=${`dt ${l.state === 'locked' ? 'x' : 'w'}`}></i>${l.name}${l.state === 'watch' ? ` ${pct(l.window_pct || 0)}` : ''}</span>`)}</button>`;
}

function FilterSheet({ snap }) {
  const groups = filterGroups(snap);
  const n = shown(snap).length;
  return html`${groups.map((g) => (g.key === 'epic' && !epicProject(snap)
    ? html`<div key="epic" class="k">Epic</div><p>Pick a project first; epics belong to one project.</p>`
    : g.items.length > 1 && html`<div key=${g.key} class="k">${g.label[0].toUpperCase() + g.label.slice(1, -1)}</div>
      <div class="chips"><${FilterChips} items=${g.items} value=${ui[g.key]} onPick=${g.pick} /></div>`))}
    <div class="row2"><button onClick=${() => set({ project: 'all', epic: 'all', machine: 'all' })}>Clear</button>
      <button class="pri" onClick=${back}>Show ${n} bead${n === 1 ? '' : 's'}</button></div>`;
}

// §9 quick actions: an ask card carries its recommended answer and More; a look card Approve and its screens; a stuck
// card asks for the reason (in the bead page)
function quick(snap) {
  return (b) => {
    const stop = (f) => (e) => { e.stopPropagation(); f(); };
    if (b.marker === 'stuck' || b.marker === 'exited') {
      return html`<div class="qa"><button class="pri bad" onClick=${stop(() => openBead(b))}>${b.cause ? `Reason: ${b.cause.replace('_', ' ')}` : 'Why did it stop? Pick a reason'}</button></div>`;
    }
    const ask = askOf(snap, b);
    if (!ask) return null;
    if (ask.source === 'look') {
      return html`<div class="qa"><button class="pri ok" onClick=${stop(() => act.look(ask, 'good'))}>✅ Approve → land</button>
        <button onClick=${stop(() => { openBead(b); set({ dtab: 'bead' }); })}>📸 ${ask.shots.length}</button></div>`;
    }
    const i = ask.options.findIndex((o) => o.recommended);
    if (i < 0) return html`<div class="qa"><button onClick=${stop(() => openBead(b))}>Answer…</button></div>`;
    const o = ask.options[i];
    return html`<div class="qa"><button class="pri" onClick=${stop(() => { act.answer(ask, i); set({ sheet: { kind: 'stick', ask: ask.id } }, { push: true }); })}>
        ✅ ${o.label}<small>${ask.blocking ? 'recommended' : 'running default'} · ${o.consequence}</small></button>
      <button onClick=${stop(() => openBead(b))}>More</button></div>`;
  };
}

// after an answer: ✓ Sent · <bead> resumes · Undo, then the five make-it-stick rows (§9)
function StickSheet({ arg }) {
  const held = ui.hold && ui.hold.ask.id === arg.ask ? ui.hold : null;
  const s = ui.sent[arg.ask];
  const ask = held ? held.ask : s && s.ask;
  if (!ask) return html`<p>Undone · nothing was sent.</p><button class="wide" onClick=${back}>Done</button>`;
  const secs = held ? Math.max(1, Math.ceil((held.until - Date.now()) / 1000)) : 0;
  return html`<div class="ok1"><i>✓</i>${held ? `Sending in ${secs}s` : 'Sent'}</div>
    <p>${bid(ask.bead, ask.project)} ${ask.blocking ? 'resumes in its slot' : 'keeps going'}. ${held && html`<button class="lnk" onClick=${act.undo}>Undo</button>`}</p>
    <div class="k">Make it stick? Optional, never blocks.</div>
    <div class="rows">${STICKS.map(([k, i, t, d]) => html`<button key=${k} class=${s && s.stick === k ? 'on' : ''} disabled=${!s || !!s.stick}
      onClick=${() => act.stick(ask.id, k)}><span class="si">${i}</span><span>${t}<small>${d}</small></span></button>`)}</div>
    <button class="wide" onClick=${back}>Done</button>`;
}

const hasFilters = (snap) => filterGroups(snap).some((g) => g.items.length > 1);

function BoardTab({ snap, now }) {
  const f = filterLabel(snap);
  return html`<div class="sub"><div class="sg2"><button class=${ui.opt !== 'tree' ? 'on' : ''} onClick=${() => set({ opt: '', gp: [] })}>Flow</button>
      <button class=${ui.opt === 'tree' ? 'on' : ''} onClick=${() => set({ opt: 'tree', gp: [] })}>Goals</button></div>
      ${hasFilters(snap) && html`<button class=${`flt ${f.length ? 'on' : ''}`} onClick=${() => set({ sheet: { kind: 'filter' } }, { push: true })}>Filter${f.length ? ` · ${f.length}` : ''}</button>`}</div>
    ${f.length > 0 && html`<div class="fsum"><span>${f.join(' · ')}</span><button onClick=${() => set({ project: 'all', epic: 'all', machine: 'all' })}>Clear</button></div>`}
    ${ui.opt === 'tree' ? html`<${PhoneGoals} snap=${snap} />` : html`<${PhoneFlow} snap=${snap} now=${now} onOpen=${openBead} actions=${quick(snap)} />`}`;
}

// a swipe from the left edge goes back (the bead page); plain listeners, since Preact names touch events by whether the
// browser has touch at all
function useEdgeSwipe(ref) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let x0 = -1, y0 = 0;
    const start = (e) => { const t = e.touches[0]; x0 = t.clientX < 24 ? t.clientX : -1; y0 = t.clientY; };
    const end = (e) => {
      const t = e.changedTouches[0];
      if (x0 >= 0 && t.clientX - x0 > 80 && Math.abs(t.clientY - y0) < 60) back();
      x0 = -1;
    };
    el.addEventListener('touchstart', start, { passive: true });
    el.addEventListener('touchend', end);
    return () => { el.removeEventListener('touchstart', start); el.removeEventListener('touchend', end); };
  }, []);
}

const SHEETS = { filter: ['Filter', FilterSheet], stick: ['', StickSheet], stop: ['', StopSheet], note: ['', NoteSheet] };

export function Phone({ snap, now }) {
  const pg = useRef(null);
  useEdgeSwipe(pg);
  const c = counts(snap), card = findBead(snap, ui.bead);
  const sheet = ui.sheet && SHEETS[ui.sheet.kind];
  let body;
  if (ui.tab === 'board') body = html`<${BoardTab} snap=${snap} now=${now} />`;
  else if (ui.tab === 'decisions') body = html`<${Decisions} snap=${snap} now=${now} phone />`;
  else if (ui.tab === 'floor') body = html`<${PhoneFloor} snap=${snap} now=${now} />`;
  else body = html`<${PhoneLanes} snap=${snap} now=${now} />`;
  return html`<div id="ph">
    <header class="ph-h"><h1>${TABS.find((t) => t[0] === ui.tab)[2]}</h1><${LanePill} snap=${snap} /></header>
    <${Banners} snap=${snap} now=${now} />
    <main id="phM">${ui.tab === 'board' && html`<${Needs} snap=${snap} now=${now} />`}${body}</main>
    <nav class="tb">${TABS.map(([k, e, n]) => html`<button key=${k} class=${ui.tab === k ? 'on' : ''} onClick=${() => setTab(k)}>
      <i>${e}</i>${n}${k === 'floor' && html`<span class=${`bd r ${c.stuck ? 'on' : ''}`}>${c.stuck}</span>`}${k === 'decisions' && html`<span class=${`bd b ${c.asks ? 'on' : ''}`}>${c.asks}</span>`}</button>`)}</nav>
    <div class=${`pg ${card ? 'on' : ''}`} ref=${pg}>${card && html`<${BeadPage} key=${card.project + card.id} snap=${snap} card=${card} now=${now} phone />`}</div>
    <${Sheet} open=${!!sheet} title=${sheet && sheet[0]} onClose=${back}>${sheet && html`<${sheet[1]} snap=${snap} now=${now} arg=${ui.sheet} />`}</${Sheet}>
  </div>`;
}
