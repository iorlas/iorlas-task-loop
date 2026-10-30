// The shell: top bar, tabs, filters, banners and states (dash-spec §2.1, §10). Below 600 px the phone shell (views/phone.js)
// takes over: the same data and renderers, its own layout (§9).
import { html, render, useEffect, useState } from '../vendor/ui-runtime.js';
import * as act from './actions.js';
import * as api from './api.js';
import { setManyProjects } from './format.js';
import { counts, troubled, bead as findBead } from './data.js';
import { rememberScroll, scrollOf, set, subscribe, ui, setTab } from './state.js';
import { CountBadge, Drawer, EmptyState, FilterChips, Ring, Tabs, Toast } from './ui/kit.js';
import { Flow } from './views/board.js';
import { Decisions } from './views/decisions.js';
import { BeadPage } from './views/drawer.js';
import { Phone } from './views/phone.js';
import { Floor } from './views/floor.js';
import { Goals } from './views/goals.js';
import { Lanes } from './views/lanes.js';
import { Cost } from './views/cost.js';
import { Banners, closeBead, filterGroups, laneValue, openBead, STALE_S, TABS } from './views/shell.js';

const PHONE = matchMedia('(max-width:600px)');
const TICK_MS = 1000;

function useRender() {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    const offs = [subscribe(f), api.onData(f)];
    const t = setInterval(f, TICK_MS);
    PHONE.addEventListener('change', f);
    return () => { offs.forEach((o) => o()); clearInterval(t); PHONE.removeEventListener('change', f); };
  }, []);
}

function Filters({ snap }) {
  return filterGroups(snap).map((g) => html`<${FilterChips} key=${g.key} label=${g.label} items=${g.items} value=${ui[g.key]} onPick=${g.pick} />`);
}

function TopRight({ snap, now }) {
  const a = api.dataAge(), tone = api.net.error ? 'x' : a > STALE_S ? 'w' : '';
  return html`<div class="rt">
    ${troubled(snap).map((l) => html`<button key=${l.id} class="rbtn" onClick=${() => setTab('lanes')}><${Ring} v=${l.state === 'locked' ? 1 : (l.window_pct || 0) / 100}
        tone=${l.state === 'locked' ? 'x' : 'w'} value=${laneValue(l, now)} label=${l.name} /></button>`)}
    <button class="lbtn" onClick=${() => setTab('lanes')}>${snap.lanes.length} lanes ▾</button>
    <button class="rbtn" title=${`Data ${Math.round(a)} s old · refresh`} onClick=${api.retry}><${Ring} tone=${tone} value=${`${Math.round(a)}s`} /></button></div>`;
}

function Desktop({ snap, now }) {
  const c = counts(snap), all = ui.project === 'all';
  const tabs = TABS.map(([k, e, n]) => ({ k, label: `${e} ${n}`,
    badge: k === 'floor' ? html`<${CountBadge} n=${c.stuck} tone="bad" />` : k === 'decisions' ? html`<${CountBadge} n=${c.asks} />` : null }));
  const card = findBead(snap, ui.bead);
  let body;
  if (ui.tab === 'board') {
    body = html`<div class="bbar"><span class="seg"><button class=${ui.opt !== 'tree' ? 'on' : ''} onClick=${() => set({ opt: '' })}>Flow</button>
        <button class=${ui.opt === 'tree' ? 'on' : ''} onClick=${() => set({ opt: 'tree' })}>Goals</button></span><${Filters} snap=${snap} /></div>
      ${ui.opt === 'tree' ? html`<${Goals} snap=${snap} all=${all} />` : html`<${Flow} snap=${snap} all=${all} now=${now} onOpen=${openBead} />`}`;
  } else if (ui.tab === 'decisions') {
    body = html`<${Decisions} snap=${snap} now=${now} />`;
  } else if (ui.tab === 'floor') {
    body = html`<${Floor} snap=${snap} now=${now} filters=${html`<${Filters} snap=${snap} />`} />`;
  } else if (ui.tab === 'cost') {
    body = html`<${Cost} snap=${snap} />`;
  } else {
    body = html`<${Lanes} snap=${snap} now=${now} />`;
  }
  return html`<div class="app">
    <div class="top"><span class="brand">task-loop</span><${Tabs} cls="nav" items=${tabs} value=${ui.tab} onPick=${setTab} />
      <${TopRight} snap=${snap} now=${now} /></div>
    <${Banners} snap=${snap} now=${now} />
    <main class="main">${body}</main>
    <${Drawer} open=${!!card} wide=${ui.wide} onClose=${closeBead} onWide=${() => set({ wide: !ui.wide })}>
      ${card && html`<${BeadPage} key=${card.project + card.id} snap=${snap} card=${card} all=${all} now=${now} />`}</${Drawer}>
  </div>`;
}

function useScroll(snap) {
  const place = `w:${PHONE.matches ? 'p' : 'd'}:${ui.tab}`;
  useEffect(() => {
    if (!snap) return undefined;
    scrollTo(0, scrollOf(place));
    const f = () => rememberScroll(place, scrollY);
    addEventListener('scroll', f, { passive: true });
    return () => removeEventListener('scroll', f);
  }, [place, !!snap]);
}

function App() {
  useRender();
  const snap = api.net.snap, now = api.now();
  useScroll(snap);
  document.documentElement.classList.toggle('phone', PHONE.matches);
  if (!snap) {
    return api.net.error ? html`<div class="ban bad">Server unreachable (${api.net.error}) · retrying</div>`
      : html`<p class="loading">Loading…</p>`;
  }
  act.prune();
  setManyProjects(snap.projects.length > 1);
  const c = counts(snap);
  document.title = c.asks + c.stuck ? `(${c.asks + c.stuck}) task-loop` : 'task-loop';
  if (!snap.beads.length) {
    return html`<${EmptyState} title="No beads yet" body=${snap.projects.length ? 'Create beads with bd, then start the loop.' : 'Register a repo, then start its loop.'}
      cmd=${snap.projects.length ? 'tl run' : 'tl register <repo>  ·  tl run'} />`;
  }
  const red = snap.projects.filter((p) => p.profile_error).map((p) => html`<div class="ban bad">${p.profile_error}</div>`);
  return html`<div class=${api.net.error ? 'greyed' : ''}>${red}${PHONE.matches ? html`<${Phone} snap=${snap} now=${now} />` : html`<${Desktop} snap=${snap} now=${now} />`}
    <${Toast} toast=${ui.toast} /></div>`;
}

render(html`<${App} />`, document.getElementById('root'));
api.start();
