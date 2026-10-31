// Shell parts both shells share: tabs, banners, filter groups, the lane value, opening a bead (dash-spec §2, §10).
import { html } from '../../vendor/ui-runtime.js';
import * as api from '../api.js';
import { epicsOf, machines, MACHINE_ICON } from '../data.js';
import { age, pct, unit } from '../format.js';
import { set, ui } from '../state.js';

export const STALE_S = 30, STALE_BANNER_S = 300;
export const TABS = [['board', '🗂️', 'Board'], ['floor', '🏭', 'Floor'], ['decisions', '🙋', 'Decisions'], ['lanes', '🎛', 'Lanes'], ['cost', '💲', 'Cost']];

// §10: unreachable (red line, retry with backoff, last data greyed), stale > 5 min, loop not running
export function Banners({ snap, now }) {
  const out = [];
  if (api.net.error && snap) {
    out.push(html`<div key="down" class="ban bad">Server unreachable (${api.net.error}); showing the last data from ${age(now - api.dataAge(), now)} ago ·
      <button class="lnk" onClick=${api.retry}>Retry</button></div>`);
  } else if (api.dataAge() > STALE_BANNER_S) {
    out.push(html`<div key="stale" class="ban watch">No refresh for ${age(now - api.dataAge(), now)} · <button class="lnk" onClick=${api.retry}>Refresh</button></div>`);
  }
  for (const l of snap.server.loops.filter((x) => !x.running)) {
    out.push(html`<div key=${`loop-${l.project}`} class="ban watch">Loop not running on ${l.project}${l.last_activity ? ` · last activity ${age(l.last_activity, now)} ago` : ''} · start it: <code>tl loop</code> · one task: <code>tl run-task ID</code></div>`);
  }
  return out;
}

// project → epic (after a project is picked, with a done-share meter) → machine; each hidden with one value (§2.2)
// the project whose epics the filter offers: the picked one, or the only one
export const epicProject = (snap) => (ui.project !== 'all' ? ui.project : snap.projects.length === 1 ? snap.projects[0].id : null);

export function filterGroups(snap) {
  const p = epicProject(snap), epics = p ? epicsOf(snap, p) : [];
  const epicItems = epics.map((e) => ({ k: e.id, n: e.title, meter: e.total ? e.done / e.total : 0 }));
  const hasClosed = !!p && snap.epics.some((e) => e.project === p && !e.open);
  if (hasClosed) {
    epicItems.push({ k: 'show-closed', n: ui.showClosed ? 'Hide closed' : 'Show closed' });
  }
  return [
    { key: 'project', label: 'projects', items: snap.projects.map((p) => ({ k: p.id, n: p.name })), pick: (k) => set({ project: k, epic: 'all' }) },
    { key: 'epic', label: 'epics', items: epicItems, keep: hasClosed,
      pick: (k) => set(k === 'show-closed' ? { showClosed: !ui.showClosed } : { epic: k }) },
    { key: 'machine', label: 'machines', items: machines(snap).map((m) => ({ k: m, n: `${MACHINE_ICON(m)} ${m}` })), pick: (k) => set({ machine: k }) },
  ];
}

export const laneValue = (l, now) => (l.state === 'locked' ? (l.locked_until ? unit(l.locked_until - now) : 'out') : pct(l.window_pct || 0));

export const openBead = (b) => set({ bead: b.id, dtab: '', ...(ui.project === 'all' ? {} : { project: b.project }) }, { push: !ui.bead });
export const closeBead = () => set({ bead: null, dtab: '' });

