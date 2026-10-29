// Lanes (dash-spec §8): one row per subscription lane, worst first: a ring with the number inside, the 5 h window with the
// hatched forecast to the reset, the week, the forecast in words, slots, running and waiting beads. A lane whose status is
// older than 1 h is greyed with its age. Numbers come from delegate's usage feed; the page never calls a vendor.
import { html } from '../../vendor/ui-runtime.js';
import { lanesSorted, bead as findBead } from '../data.js';
import { MARK, age, bid, clock, pct, unit } from '../format.js';
import { ui } from '../state.js';
import { Ring } from '../ui/kit.js';
import { laneValue, openBead } from './shell.js';

const STALE_S = 3600;
const TONE = { locked: 'x', watch: 'w' };
const stale = (l, now) => l.state === 'stale' || (l.status_t != null && now - l.status_t > STALE_S);

function Bar({ v, p, tone }) {
  const used = Math.min(100, v || 0), fc = Math.min(100, p || 0);
  return html`<div class="ub"><span class="bar"><i class=${tone} style=${`width:${used}%`}></i>${fc > used && html`<b style=${`left:${used}%;width:${fc - used}%`}></b>`}</span>
    <span>${v == null ? '—' : pct(v)}</span></div>`;
}

function Chips({ snap, ids, wait }) {
  if (!ids.length) return html`<span class="mu">—</span>`;
  return ids.map((id) => {
    const b = findBead(snap, id);
    return html`<button key=${id} class="chip" disabled=${!b} onClick=${() => b && openBead(b)}>${wait ? '▷' : b ? MARK[b.marker] : '·'} ${b ? bid(b.id, b.project, ui.project === 'all') : id}${wait ? ' waits' : ''}</button>`;
  });
}

const ring = (l, now, size) => html`<${Ring} v=${l.state === 'locked' ? 1 : (l.window_pct || 0) / 100} tone=${TONE[l.state] || ''} value=${laneValue(l, now)} size=${size} />`;
const when = (t, now) => (t - now < 20 * 3600 ? clock(t) : `in ${unit(t - now)}`);
const resets = (l, now) => (l.state === 'locked' ? (l.locked_until ? `unlocks ${when(l.locked_until, now)}` : 'locked')
  : l.resets_at ? `resets ${when(l.resets_at, now)}` : '');
const staleNote = (l, now) => html`<span class="stl">${l.status_t != null ? `updated ${age(l.status_t, now)} ago · ` : ''}run <code>tl lanes</code></span>`;

export function Lanes({ snap, now }) {
  const L = lanesSorted(snap);
  return html`<div class="lanes2"><table class="lt"><thead><tr><th>lane</th><th class="w5">5 h window <span class="lo">· hatched = forecast</span></th>
      <th class="wk">week</th><th>forecast</th><th>slots</th><th>running</th><th>waiting for it</th></tr></thead>
    <tbody>${L.map((l) => html`<tr key=${l.id} class=${stale(l, now) ? 'stale' : ''}>
      <td><div class="nm">${ring(l, now, 44)}<div>${l.name}<small>${[l.plan, l.model].filter(Boolean).join(' · ')}</small></div></div></td>
      <td><${Bar} v=${l.window_pct} p=${l.forecast_pct} tone=${TONE[l.state] || ''} /><div class="mu">${resets(l, now)}</div></td>
      <td><${Bar} v=${l.week_pct} p=${l.week_pct} tone=${(l.week_pct || 0) >= 100 ? 'x' : ''} /></td>
      <td class=${`fx ${TONE[l.state] || ''}`}>${l.forecast}${stale(l, now) && html`<br />${staleNote(l, now)}`}</td>
      <td class="mu sls">${l.slots.length ? l.slots.map((s) => html`<div key=${s}>${s}</div>`) : '—'}</td>
      <td class="bd"><${Chips} snap=${snap} ids=${l.running} /></td><td class="bd"><${Chips} snap=${snap} ids=${l.waiting} wait /></td></tr>`)}</tbody></table>
    <p class="lsec">Sorted: locked first, then running out, then fine. The top bar shows only lanes that are not fine. Numbers come from delegate's usage feed (refreshed by the loop every 20 min).</p></div>`;
}

export function PhoneLanes({ snap, now }) {
  return html`<div class="pl lanesp">${lanesSorted(snap).map((l) => html`<div key=${l.id} class=${`lc ${stale(l, now) ? 'stale' : ''}`}>
      <div class="rg">${ring(l, now, 46)}</div>
      <div><div class="lnm">${l.name}<small>${l.plan}</small></div>
        <div class="lm">${[resets(l, now), l.slots.join(', ')].filter(Boolean).join(' · ')}</div>
        <${Bar} v=${l.window_pct} p=${l.forecast_pct} tone=${TONE[l.state] || ''} />
        <div class=${`fx ${TONE[l.state] || ''}`}>${l.forecast}</div>
        ${stale(l, now) && html`<div class="lm">${staleNote(l, now)}</div>`}
        ${(l.running.length > 0 || l.waiting.length > 0) && html`<div class="bx">${l.running.length > 0 && html`<${Chips} snap=${snap} ids=${l.running} />`}${l.waiting.length > 0 && html`<${Chips} snap=${snap} ids=${l.waiting} wait />`}</div>`}</div>
    </div>`)}</div><p class="hint3">Hatched = forecast to the reset at this burn rate.</p>`;
}
