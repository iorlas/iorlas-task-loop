// Decisions (dash-spec §7): "Is the factory learning?" on top, then Waiting on you · Ledger · Decisions in force. Waiting
// holds the open ask cards whole, the same card as the drawer; an ask answered here stays with its "make it stick" row.
import { html, useState } from '../../vendor/ui-runtime.js';
import * as act from '../actions.js';
import { answered, bead as findBead } from '../data.js';
import { age, bid, day, pct } from '../format.js';
import { set, ui } from '../state.js';
import { AskCard, CAUSES, LookCard, STICKS } from '../ui/ask.js';
import { EmptyState, FilterChips, Spark, Tabs } from '../ui/kit.js';
import { epicProject, openBead } from './shell.js';

function Card({ snap, ask, now }) {
  const b = findBead(snap, ask.bead, ask.project);
  const h = act.hooks(ask);
  const head = html`<div class="bt"><span>${bid(ask.bead, ask.project, ui.project === 'all')}${b ? ` · ${b.title}` : ''} · waited ${age(ask.t, now)}</span>
    ${b && html`<button class="lnk" onClick=${() => openBead(b)}>open bead →</button>`}</div>`;
  return html`<div class="wcard">${head}${ask.source === 'look' ? html`<${LookCard} ask=${ask} now=${now} ...${h.look} />`
    : html`<${AskCard} ask=${ask} now=${now} ...${h.ask} />`}</div>`;
}

function Waiting({ snap, now }) {
  const open = snap.asks.filter((a) => (ui.project === 'all' || a.project === ui.project) && (!answered(a) || ui.sent[a.id] || (ui.hold && ui.hold.ask.id === a.id)));
  const gone = Object.values(ui.sent).map((s) => s.ask).filter((a) => !open.some((o) => o.id === a.id));
  const cards = [...open, ...gone];
  if (!cards.length) return html`<${EmptyState} title="Nothing waits on you." body="Asks and looks show here whole, the same card as in the bead." />`;
  return html`<div class="asks">${cards.map((a) => html`<${Card} key=${a.id} snap=${snap} ask=${a} now=${now} />`)}</div>`;
}

// ---- "Is the factory learning?" (§7.1): four weekly stats and the cause Pareto, numbers from the server

const STATS = [
  ['asks_per_landed', 'asks per landed bead', 'fewer questions per finished bead', 'down', (v) => v.toFixed(1)],
  ['repeat_asks', 'repeat asks', 'asked again though an answer existed', 'down', String],
  ['sendbacks_per_bead', 'send-backs per bead', 'guard: fewer asks, not more guessing', 'down', (v) => v.toFixed(1)],
  ['durable_pct', 'asks made durable', 'became a decision or a fix', 'up', (v) => pct(v)],
];

function Stat({ series, label, why, good, fmt }) {
  if (!series.length) return html`<div class="st4"><div class="l">${label}</div><div class="nv">—</div><div class="why">${why}</div></div>`;
  const cur = series[series.length - 1], prev = series.length > 1 ? series[series.length - 2] : cur;
  const tone = cur === prev ? 'flat' : (cur < prev) === (good === 'down') ? 'good' : 'bad';
  const d = cur === prev ? '→ same' : `${cur < prev ? '↓' : '↑'} from ${fmt(prev)}`;
  return html`<div class="st4"><div class="l">${label}</div><div class="nv">${fmt(cur)}<span class=${`d ${tone}`}>${d}</span></div>
    <${Spark} v=${series} tone=${tone} /><div class="why">${why}</div></div>`;
}

function Learning({ l }) {
  const causes = [...l.causes].sort((a, b) => b.now - a.now);
  const mx = Math.max(1, ...causes.map((c) => c.now));
  return html`<h2><b>Is the factory learning?</b>last 8 weeks · this week vs last</h2>
    <div class="learn"><div class="stats">${STATS.map(([k, label, why, good, fmt]) => html`<${Stat} key=${k} series=${l[k]} label=${label} why=${why} good=${good} fmt=${fmt} />`)}</div>
      <div class="causes"><div class="l">why agents asked or stopped</div><div class="par">${causes.map((c) => {
        const d = c.now - c.prev, q = c.cause === 'unknown';
        return html`<span key=${c.cause} class=${q ? 'q' : ''}>${CAUSES[c.cause]}</span><span class="bar"><i class=${q ? 'q' : ''} style=${`width:${(c.now / mx) * 100}%`}></i></span>
          <span class="c">${c.now}</span><span class=${`d ${d > 0 ? 'bad' : d < 0 ? 'good' : 'flat'}`}>${d > 0 ? `↑${d}` : d < 0 ? `↓${-d}` : '→'}</span>`;
      })}${!causes.length && html`<span class="mu">no asks or stops yet</span>`}</div></div></div>`;
}

// ---- Ledger (§7.2): every ask, one line; filter chips; make it stick on an answered row with no outcome

const OUTCOME = { adr: '📜 Decision', ref: '🔗 Already decided', factory: '🛠 Factory bead', fix: '✏️ Bead fixed', demote: '⬇ No longer blocks', once: 'Once' };
const LEDGER_FILTERS = [...Object.entries(OUTCOME), ['open', 'Open'], ['unknown', '? No cause']].map(([k, n]) => ({ k, n }));
const ASK_CAUSES = ['requirement', 'decision', 'environment', 'process'];

function ledgerMatch(r, f, outcome) {
  if (f === 'all') return true;
  if (f === 'open') return r.status !== 'answered';
  if (f === 'unknown') return r.cause === 'unknown';
  return outcome === f;
}

function LedgerRow({ r, now }) {
  const [pick, setPick] = useState(''); // '' | 'stick' | 'cause'
  const [cause, setCause] = useState(r.cause);
  const outcome = r.outcome || ui.outcomes[r.ask];
  let oc;
  if (outcome) oc = html`${OUTCOME[outcome]}${r.outcome_ref && html` <span class="a">${r.outcome_ref}</span>`}`;
  else if (r.status !== 'answered') oc = html`<span class="you">waiting on you</span>`;
  else if (pick === 'stick') oc = html`<span class="why">${STICKS.map(([k, i, t]) => html`<button key=${k} class="fc" onClick=${() => { setPick(''); act.stickRow(r, k); }}>${i} ${t}</button>`)}</span>`;
  else oc = html`<button class="fc" onClick=${() => setPick('stick')}>make it stick</button>`;
  const cc = pick === 'cause' ? html`<span class="why">${ASK_CAUSES.map((c) => html`<button key=${c} class="fc"
      onClick=${() => { setPick(''); setCause(c); act.cause(r.project, r.bead, c, r.ask); }}>${CAUSES[c]}</button>`)}</span>`
    : cause === 'unknown' ? html`<button class="lnk q" onClick=${() => setPick('cause')}>? name it</button>` : CAUSES[cause];
  return html`<tr><td class="mu">${day(r.t, now)}</td><td class="mu">${bid(r.bead, r.project, ui.project === 'all')}</td>
    <td class="qq"><span>${r.question}</span>${r.answer && html` <span class="a">→ ${r.answer}</span>`}</td><td class="oc">${oc}</td>
    <td class=${`mu ${cause === 'unknown' ? 'q' : ''}`}>${cc}</td></tr>`;
}

function Ledger({ snap, now }) {
  const rows = snap.ledger.filter((r) => (ui.project === 'all' || r.project === ui.project) && ledgerMatch(r, ui.ledger, r.outcome || ui.outcomes[r.ask]));
  return html`<div class="chips"><${FilterChips} keep items=${LEDGER_FILTERS} value=${ui.ledger}
      onPick=${(v) => set({ ledger: v })} /></div>
    ${rows.length ? html`<table class="led"><tbody>${rows.map((r) => html`<${LedgerRow} key=${r.ask} r=${r} now=${now} />`)}</tbody></table>`
      : html`<p class="hint2">Nothing here.</p>`}`;
}

// ---- Decisions in force (§7.2): reuse = plans that cited it; 0 reuses in 30 days is amber and offers prune

// prune asks once inline (a retired decision has no way back from the page), then sends PruneReq
function Prune({ a, project }) {
  const [ask, setAsk] = useState(false);
  if (!ask) return html`<button class="lnk warn" title="Retire this decision" onClick=${() => setAsk(true)}>prune?</button>`;
  return html`<span class="why">retire? <button class="fc" onClick=${() => act.pruneAdr(project, a.id)}>Yes</button>
    <button class="fc" onClick=${() => setAsk(false)}>No</button></span>`;
}

function InForce({ snap, now }) {
  const fallback = epicProject(snap) || '';
  const adrs = snap.adrs.map((a) => ({ a, project: a.project || fallback }))
    .filter(({ a, project }) => (ui.project === 'all' || !a.project || a.project === ui.project) && !ui.pruned[`${project}/${a.id}`]);
  if (!adrs.length) return html`<${EmptyState} title="No decisions recorded yet." body="Answer an ask and pick 📜 Record a decision; agents read these at plan." />`;
  const many = ui.project === 'all' && new Set(adrs.map(({ a }) => a.project)).size > 1;
  return html`<p class="hint2">Agents read these at plan; tl ask checks them before asking you. A decision nobody reused in 30 days offers prune.</p>
    <div class="adr">${adrs.map(({ a, project }) => {
      const k = `${project}/${a.id}`;
      return html`<div key=${`i${k}`} class="mu">${many && a.project ? `${a.project} · ` : ''}${a.id}</div><div key=${`t${k}`}>${a.text}</div>
      <div key=${`r${k}`} class=${`mu ${a.prune ? 'z' : ''}`}>${a.reuses} reuse${a.reuses === 1 ? '' : 's'}${a.last_used ? ` · last ${day(a.last_used, now)}` : ''}</div>
      <div key=${`a${k}`} class=${`mu ${a.prune ? 'z' : ''}`}>${a.prune ? html`<${Prune} a=${a} project=${project} />` : `${age(a.t, now)} old`}</div>`;
    })}</div>`;
}

export const waitingCount = (snap) => snap.asks.filter((a) => !answered(a)).length;

// the tab opens on Waiting when something waits, otherwise on Ledger
export const decisionsTab = (snap) => (['wait', 'led', 'adr'].includes(ui.opt) ? ui.opt : waitingCount(snap) ? 'wait' : 'led');

export function Decisions({ snap, now, phone }) {
  const tab = decisionsTab(snap);
  const n = waitingCount(snap);
  const items = [
    { k: 'wait', label: html`${phone ? 'Waiting' : 'Waiting on you'} <span class=${n ? 'nb' : 'cnt'}>${n}</span>` },
    { k: 'led', label: html`Ledger${phone ? '' : html` <span class="cnt">${snap.ledger.length}</span>`}` },
    { k: 'adr', label: html`${phone ? 'In force' : 'Decisions in force'}${phone ? '' : html` <span class="cnt">${snap.adrs.length}</span>`}` },
  ];
  const body = tab === 'wait' ? html`<${Waiting} snap=${snap} now=${now} />` : tab === 'led' ? html`<${Ledger} snap=${snap} now=${now} />`
    : html`<${InForce} snap=${snap} now=${now} />`;
  return html`<div class="dec"><${Learning} l=${snap.learning} />
    <${Tabs} cls="dtabs" items=${items} value=${tab} onPick=${(k) => set({ opt: k })} />${body}</div>`;
}
