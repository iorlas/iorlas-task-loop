// Board › Goals (dash-spec §3.1): roots are beads no open bead waits on; under each, what it needs (bd needs), recursively,
// so the bottom of a branch is what runs now. A bead needed twice shows once in full, elsewhere as a ⤴ stub. A folded
// branch shows its roll-up ▶n 🙋n 🛑n. The phone drills down one level at a time instead (§9), each level a history entry.
import { html } from '../../vendor/ui-runtime.js';
import { idx, key, visible } from '../data.js';
import { MARK } from '../format.js';
import { fold, set, ui } from '../state.js';
import { BeadRow, EmptyState } from '../ui/kit.js';
import { openBead } from './shell.js';

const STATE = { stuck: 'stuck', exited: 'stuck', ask: 'ask', look: 'you', soft_ask: 'you', run: 'run', parked: 'run', blocked: 'blocked', ready: 'ready', done: 'done' };
const ORDER = { stuck: 0, ask: 1, you: 2, run: 3, blocked: 4, ready: 5, done: 6 };
const rank = (b) => ORDER[STATE[b.marker]] ?? 5;
const byRank = (a, b) => rank(a) - rank(b);

function graph(snap) {
  const beads = idx(snap).beads;
  const get = (b, id) => beads.get(key(b.project, id));
  const kids = (b) => b.needs.map((id) => get(b, id)).filter(Boolean).sort(byRank);
  const waited = new Set();
  for (const b of snap.beads) if (b.column !== 'done') for (const n of b.needs) waited.add(key(b.project, n));
  const roots = snap.beads.filter((b) => b.column !== 'done' && !waited.has(key(b.project, b.id)) && (visible(snap, b) || b.needs.length))
    .sort((a, b) => b.needs.length - a.needs.length || byRank(a, b));
  return { kids, roots };
}

// everything under a bead, each once
function below(b, kids) {
  const out = new Map();
  const go = (x) => kids(x).forEach((y) => { const k = key(y.project, y.id); if (!out.has(k)) { out.set(k, y); go(y); } });
  go(b);
  return [...out.values()];
}

export function rollup(b, kids) {
  const d = below(b, kids), n = (...s) => d.filter((x) => s.includes(STATE[x.marker])).length;
  return [['▶', n('run')], ['🙋', n('ask', 'you')], ['🛑', n('stuck')], ['✅', n('done')]].filter((x) => x[1]).map((x) => `${x[0]}${x[1]}`).join(' ');
}

const anchorOf = (b) => `g-${b.project}-${b.id}`.replace(/[^\w-]/g, '_');
function jump(b) {
  const el = document.getElementById(anchorOf(b));
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  el.classList.add('sel');
  setTimeout(() => el.classList.remove('sel'), 1200);
}

export function Goals({ snap, all }) {
  const { kids, roots } = graph(snap);
  if (!roots.length) return html`<${EmptyState} title="No open goals." body="Everything open is done, or filtered out." />`;
  const seen = new Set(), rows = [];
  const walk = (b, pad) => {
    const k = key(b.project, b.id), fk = `t:${k}`, ks = kids(b);
    if (seen.has(k)) {
      rows.push(html`<${BeadRow} key=${`${rows.length}s`} card=${b} all=${all} pad=${pad} twist="" onOpen=${() => jump(b)}
        extra=${html`<span class="stub">⤴ shown above</span>`} />`);
      return;
    }
    seen.add(k);
    const folded = !!ui.folds[fk];
    rows.push(html`<${BeadRow} key=${k} anchor=${anchorOf(b)} card=${b} all=${all} pad=${pad} sel=${ui.bead === b.id} onOpen=${openBead}
      twist=${ks.length ? folded : ''} onTwist=${() => fold(fk)} rollup=${folded && rollup(b, kids)} />`);
    if (!folded) ks.forEach((c) => walk(c, pad + 1));
  };
  roots.forEach((r) => walk(r, 0));
  const done = snap.beads.filter((b) => b.column === 'done' && visible(snap, b)).length;
  return html`<div class="tree"><p class="hint">Top = what a line of work ends in. Under it, what it needs. The bottom of each branch runs now. ▸ folds a branch and shows its roll-up.</p>
    ${rows}<div class="tr done nolink"><span class="tw"></span><span class="mk">✅</span><span class="sl">${done} done today</span></div></div>`;
}

// ---- phone: one level at a time; ui.gp is the path of opened goals

const icon = (b) => (b.goal ? '🎯' : MARK[b.marker]);

export function PhoneGoals({ snap }) {
  const { kids, roots } = graph(snap);
  const find = (id) => snap.beads.find((b) => b.id === id && (ui.project === 'all' || b.project === ui.project)) || null;
  const path = ui.gp.map(find);
  const top = path.length ? path[path.length - 1] : null;
  if (ui.gp.length && !top) return html`<button class="crumb" onClick=${() => history.back()}>‹ All goals</button><${EmptyState} title="That goal is gone from the board." />`;
  const list = top ? kids(top) : roots;
  const parent = path.length > 1 ? path[path.length - 2] : null;
  const head = top ? html`<button class="crumb" onClick=${() => history.back()}>‹ ${parent ? parent.title : 'All goals'}</button>
      <div class="gh"><div class="gt">${icon(top)} ${top.title}</div><div class="s">${top.id} · needs ${top.needs.length}${rollup(top, kids) ? ` · ${rollup(top, kids)}` : ''}</div>
        <button class="lnk" onClick=${() => openBead(top)}>Open bead ›</button></div>`
    : html`<p class="hint3">What each line of work ends in. Tap one to see what it needs.</p>`;
  const go = (b) => (b.needs.length ? set({ gp: [...ui.gp, b.id] }, { push: true }) : openBead(b));
  return html`${head}<div class="pl">${list.map((b) => {
    const n = b.needs.length;
    return html`<div key=${key(b.project, b.id)} class=${`gr ${STATE[b.marker] || ''}`} role="button" onClick=${() => go(b)}>
      <span class="e">${icon(b)}</span><div><div class="t">${b.title}</div><div class="s">${b.id} · ${n ? rollup(b, kids) || `needs ${n}` : b.status}</div></div>
      ${n > 0 && html`<span class="chev">›</span>`}</div>`;
  })}${!list.length && html`<div class="gr"><div><div class="s">Nothing open.</div></div></div>`}</div>`;
}
