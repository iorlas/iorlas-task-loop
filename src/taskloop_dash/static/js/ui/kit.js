// The kit: one look per component (docs/design/dashboard/dash-kit-audit-1029.md). Components take contract records
// (src/taskloop/contracts/dash.py) and callbacks; they hold no server state and decide nothing the engine decides.
import { html, useEffect, useState } from '../../vendor/ui-runtime.js';
import { causeOf, muted, troubleOf } from '../data.js';
import { MARK, MARK_TONE, age, bid, dur, md, tokens } from '../format.js';

export function Button({ kind = '', onClick, title, disabled, children }) {
  return html`<button class=${`btn ${kind}`} title=${title} disabled=${disabled} onClick=${onClick}>${children}</button>`;
}

// "All" first, text only, no counts; hidden when there is one value or fewer (dash-spec §2.2)
export function FilterChips({ label, items, value, onPick, keep }) {
  if (items.length <= 1 && !keep) return null;
  const all = [{ k: 'all', n: 'All' }, ...items];
  return html`<span class="grp">${label && html`<span class="k">${label}</span>`}${all.map((it) => html`
    <button key=${it.k} title=${typeof it.n === 'string' ? it.n : undefined} class=${`fc ${value === it.k ? 'on' : ''}`} onClick=${() => onPick(it.k)}>
      ${it.n}${it.meter != null && html`<${Meter} v=${it.meter} chip />`}
    </button>`)}</span>`;
}

// a status: radius 4, tinted, no border; pills are for filter chips only
export function Tag({ tone = '', children }) {
  return html`<span class=${`tag ${tone}`}>${children}</span>`;
}

export function CountBadge({ n, tone = 'you' }) {
  return n ? html`<span class=${`n ${tone}`}>${n}</span>` : null;
}

// the one home of the token and time thresholds (§2.6): the tone comes from the server, the page only paints it;
// grey until the lane has 5 landed beads
export function Totals({ totals, assumptions = 0, problems = 0, onProblems }) {
  if (!totals || (!totals.secs && !totals.tokens)) return null;
  const base = totals.usual_n < 5;
  const tone = base ? 'grey' : totals.tone;
  const usual = totals.usual != null ? (base ? `usual: n=${totals.usual_n} of 5` : `usual ${tokens(totals.usual)} · n=${totals.usual_n}`) : 'no usual yet';
  return html`<span class="tot"><span>⏱ ${dur(totals.secs)}</span> · <span class=${`tk ${tone}`} title=${usual}>${tokens(totals.tokens)}</span>
    ${base && totals.usual_n > 0 && html` <small class="mut">usual: n=${totals.usual_n} of 5</small>`}
    ${assumptions > 0 && html` · <span title="assumptions recorded instead of asking">💭${assumptions}</span>`}
    ${problems > 0 && html` · <button class="lnk warn" onClick=${onProblems}>⚠${problems}</button>`}</span>`;
}

// one look: a 2 px ink underline
export function Tabs({ items, value, onPick, cls = 'tabs' }) {
  return html`<div class=${cls} role="tablist">${items.map((it) => html`
    <button key=${it.k} role="tab" aria-selected=${value === it.k} class=${`tab ${value === it.k ? 'on' : ''}`} onClick=${() => onPick(it.k)}>
      ${it.label}${it.live && html`<span class="lv"></span>`}${it.badge}
    </button>`)}</div>`;
}

export function SectionHeader({ title, sub, count, children }) {
  return html`<h2 class="sec"><b>${title}</b>${count != null && html`<span class="cnt">${count}</span>`}${sub && html`<span>${sub}</span>`}${children}</h2>`;
}

// a panel that fails alone: its error line, the other panels keep working (§10)
export function Panel({ title, sub, count, children, error, cls = '' }) {
  return html`<section class=${`panel ${cls}`}>${title && html`<${SectionHeader} title=${title} sub=${sub} count=${count} />`}
    ${error ? html`<p class="perr">⚠️ ${error}</p>` : children}</section>`;
}

export function Marker({ m, goal }) {
  return html`<span class=${`mk ${MARK_TONE[m] || ''}`} title=${m}>${goal ? '🎯' : MARK[m] || ''}</span>`;
}

// neutral ink always: state is a Tag or a marker, never bar colour (§2.3); one size
export function Meter({ v, chip }) {
  const w = Math.max(0, Math.min(100, Math.round(v * 100)));
  return html`<span class=${chip ? 'mm' : 'meter'}><i style=${`width:${w}%`}></i></span>`;
}

const DOT = { done: 'd', live: 'n', you: 'y', bad: 'x', todo: '' };

// the phase dots of a card, plus ↻N (amber, red above 2)
export function Dots({ dots, loops }) {
  if (!dots || !dots.length) return null;
  return html`<div class="dots">${dots.map((d) => html`<i key=${d.phase} class=${DOT[d.state]} title=${`${d.phase} · ${d.state}`}></i>`)}
    ${loops > 0 && html`<em class=${loops > 2 ? 'x' : ''}>↻${loops}</em>`}</div>`;
}

export const cardTone = (c) => (c.marker === 'stuck' || c.marker === 'exited' || c.tone === 'bad' ? 'bad' : c.tone === 'you' ? 'you' : '');

// the status line, as the server words it (⏩ included); an exited worker leads with 💀 (§10); a stuck bead adds "why? ?"
// until a cause is picked
export function Status({ card }) {
  const c = troubleOf(card) && causeOf(card), seen = troubleOf(card) && muted(card) && !c;
  return html`${card.marker === 'exited' ? '💀 ' : ''}${card.status}${troubleOf(card) && html` · ${c ? c.replace('_', ' ') : html`why? <b>?</b>`}${seen ? ' · 👁 seen' : ''}`}`;
}

// the Board card: meta line, title, one status line, phase dots and loops (dash-spec §3)
export function BeadCard({ card, all, now, sel, onOpen, why }) {
  return html`<div class=${`kc ${cardTone(card)} ${sel ? 'sel' : ''}`} onClick=${() => onOpen(card)} role="button" tabindex="0">
    <div class="h"><span>${bid(card.id, card.project, all)}${card.slot && card.column !== 'done' && card.column !== 'backlog' ? ` · ${card.slot}` : ''}</span>
      <span class="r">${age(card.t, now)}</span></div>
    <div class="tt">${card.goal ? '🎯 ' : ''}${card.title}</div>
    <div class="st"><${Status} card=${card} /></div>
    ${why && card.waits_why && html`<div class="ww">${card.waits_why}</div>`}
    <${Dots} dots=${card.dots} loops=${card.loops} />
  </div>`;
}

// one row of a list: tree, ranked list, waits for / unblocks
export function BeadRow({ card, all, sel, onOpen, extra, pad = 0, twist, onTwist, rollup, anchor }) {
  const tone = cardTone(card);
  return html`<div id=${anchor} class=${`tr ${tone} ${card.column === 'done' ? 'done' : ''} ${card.goal ? 'goal' : ''} ${sel ? 'sel' : ''}`}
      style=${pad ? `padding-left:${8 + pad * 22}px` : ''} onClick=${() => onOpen(card)}>
    ${twist != null && html`<button class="tw" aria-label=${twist ? 'Unfold' : 'Fold'} onClick=${(e) => { e.stopPropagation(); onTwist(); }}>${twist === '' ? '' : twist ? '▸' : '▾'}</button>`}
    <${Marker} m=${card.marker} goal=${card.goal} />
    <span class="id">${bid(card.id, card.project, all)}</span>
    <span class="tt">${card.title}</span>
    ${rollup && html`<span class="ru">${rollup}</span>`}
    <span class="sl">${extra != null ? extra : html`· <${Status} card=${card} />`}</span>
  </div>`;
}

// markdown subset, escaped before it is formatted (format.md)
export const Md = ({ text, cls = '' }) => html`<div class=${`md ${cls}`} dangerouslySetInnerHTML=${{ __html: md(text) }}></div>`;

export function MsgLine({ msg, now }) {
  return html`<div class="m"><span>${msg.icon}</span><div><div class="h">${msg.who} · ${age(msg.t, now)} ago${msg.phase ? ` · ${msg.phase}` : ''}</div>
    <${Md} cls="tx" text=${msg.md} /></div></div>`;
}

// side drawer (desktop) with ⤢ full width; closes on ×, Esc or a click outside
export function Drawer({ open, wide, onClose, onWide, children }) {
  useEffect(() => {
    if (!open) return undefined;
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', k);
    return () => removeEventListener('keydown', k);
  }, [open]);
  return html`${open && html`<div class="dscrim" onClick=${onClose}></div>`}
    <aside class=${`drw ${open ? 'open' : ''} ${wide ? 'wide' : ''}`} aria-hidden=${!open}>
    ${open && html`<div class="dctl"><button class="x" title=${wide ? 'Narrow' : 'Full width'} onClick=${onWide}>⤢</button>
      <button class="x" aria-label="Close" onClick=${onClose}>×</button></div>`}${open && children}</aside>`;
}

// bottom sheet (phone) and its scrim; the scrim closes it
export function Sheet({ open, title, onClose, children }) {
  return html`<div class=${`scrim ${open ? 'on' : ''}`} onClick=${onClose}></div>
    <div class=${`sh ${open ? 'on' : ''}`} role="dialog" aria-hidden=${!open}><div class="grab"></div>
      ${open && title && html`<h3>${title}</h3>`}${open && children}</div>`;
}

export function Popover({ label, cls = 'lbtn', children }) {
  const [open, setOpen] = useState(false);
  return html`<span class="pop"><button class=${cls} onClick=${() => setOpen(!open)}>${label}</button>
    ${open && html`<div class="popb" onClick=${() => setOpen(false)}>${children}</div>`}</span>`;
}

export function Toast({ toast }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!toast) return undefined;
    setOn(true);
    const t = setTimeout(() => setOn(false), 2600);
    return () => clearTimeout(t);
  }, [toast && toast.n]);
  return html`<div class=${`toast ${on ? 'on' : ''}`} role="status">${toast && toast.text}</div>`;
}

// first run and other "nothing yet" places: one look
export function EmptyState({ title, body, cmd }) {
  return html`<div class="empty"><p class="emt">${title}</p>${body && html`<p>${body}</p>`}${cmd && html`<code class="cmd">${cmd}</code>`}</div>`;
}

export const Nothing = () => html`<div class="none">Nothing here.</div>`;

// a ring: lanes in the top bar and the Lanes tab, the refresh circle; the value sits inside
export function Ring({ v, tone = '', value, label, size = 34 }) {
  const r = 14, c = 2 * Math.PI * r;
  const col = tone === 'x' ? 'var(--red)' : tone === 'w' ? 'var(--amb)' : 'var(--mut)';
  return html`<div class="ring" style=${size !== 34 ? `width:${size}px;height:${size}px` : ''} title=${label}><svg viewBox="0 0 34 34">
      <circle cx="17" cy="17" r=${r} fill="none" stroke="var(--cell)" stroke-width="3.5" />
      ${v != null && html`<circle cx="17" cy="17" r=${r} fill="none" stroke=${col} stroke-width="3.5" stroke-dasharray=${`${c * Math.min(1, v)} ${c}`} />`}
    </svg><b style=${tone ? `color:${col}` : ''}>${value}</b>${label && html`<small>${label}</small>`}</div>`;
}

// an 8-point sparkline in the stat colour (Decisions › learning)
export function Spark({ v, tone = 'flat', w = 120, h = 24 }) {
  if (!v || v.length < 2) return null;
  const mx = Math.max(...v), mn = Math.min(...v);
  const pts = v.map((y, i) => [i * ((w - 4) / (v.length - 1)) + 2, h - 3 - ((y - mn) / (mx - mn || 1)) * (h - 6)]);
  return html`<svg class=${`spark ${tone}`} viewBox=${`0 0 ${w} ${h}`} width=${w} height=${h}>
    <polyline points=${pts.map((p) => p.map((x) => x.toFixed(1)).join(',')).join(' ')} fill="none" stroke-width="1.5" />
    <circle cx=${pts[pts.length - 1][0]} cy=${pts[pts.length - 1][1]} r="2.5" /></svg>`;
}
