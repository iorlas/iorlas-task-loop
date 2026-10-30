// Cost (bead tl-7y6.4.9): where the time and the tokens went, summed per stage and bead over 24 h, 7 d or the last
// runs. Two stacked bars per grouping (time, tokens) over a table with the cost. A cost the worker never gave is counted in its own
// column ("n unknown"), never added as $0. Read-only: GET /api/cost.
import { html, useEffect, useState } from '../../vendor/ui-runtime.js';
import { bid, dur, tokens } from '../format.js';
import { ui } from '../state.js';
import { EmptyState } from '../ui/kit.js';

const WINDOWS = [['24h', '24 h', ''], ['7d', '7 d', ''], ['last', 'Last 10 runs', 10]];
const GROUPS = [['stages', 'Stage'], ['beads', 'Bead']];

export const money = (n) => `$${n.toFixed(n < 10 ? 2 : 0)}`;
export const costText = (r) => (r.unknown ? `${r.cost ? money(r.cost) + ' + ' : ''}${r.unknown} unknown` : money(r.cost));

function Stack({ rows, field, label }) {
  const total = rows.reduce((a, r) => a + r[field], 0);
  if (!total) return null;
  return html`<div class="cs"><span class="cl">${label}</span><span class="cbar">${rows.filter((r) => r[field]).map((r, i) => html`
    <i key=${r.key} class=${`c${i % 6}`} style=${`width:${(100 * r[field]) / total}%`} title=${`${r.key} · ${field === 'secs' ? dur(r.secs) : tokens(r.tokens)}`}></i>`)}</span></div>`;
}

function Group({ title, rows, name, drill, snap, open, onOpen }) {
  if (!rows.length) return null;
  const all = ui.project === 'all';
  return html`<section class="cg"><h3>By ${title.toLowerCase()}</h3>
    <${Stack} rows=${rows} field="secs" label="time" /><${Stack} rows=${rows} field="tokens" label="tokens" />
    <table class="ct"><thead><tr><th>${title}</th><th>time</th><th>tokens</th><th>cost</th></tr></thead><tbody>${rows.map((r, i) => {
    const dr = name === 'beads' ? drill.filter((d) => d.bead === r.key) : [];
    return html`<tr key=${r.key} class=${dr.length ? 'dr' : ''} onClick=${dr.length ? () => onOpen(open === r.key ? '' : r.key) : null}>
      <td><i class=${`sw c${i % 6}`}></i>${name === 'beads' ? bid(r.key, '', all) : r.key}${dr.length ? (open === r.key ? ' ▾' : ' ▸') : ''}</td>
      <td>${dur(r.secs)}</td><td>${tokens(r.tokens)}</td><td class=${r.unknown ? 'unk' : ''}>${costText(r)}</td></tr>
      ${open === r.key && dr.map((d) => html`<tr key=${r.key + d.key} class="sub"><td>${d.key}</td><td>${dur(d.secs)}</td><td>${tokens(d.tokens)}</td><td>${costText(d)}</td></tr>`)}`;
  })}</tbody></table></section>`;
}

export function Cost({ snap }) {
  const [win, setWin] = useState('24h'), [page, setPage] = useState(null), [err, setErr] = useState(''), [open, setOpen] = useState('');
  const w = WINDOWS.find((x) => x[0] === win);
  useEffect(() => {
    let on = true;
    const q = `window=${win === 'last' ? '7d' : win}&last=${w[2] || 0}${ui.project === 'all' ? '' : `&project=${encodeURIComponent(ui.project)}`}`;
    fetch(`/api/cost?${q}`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p) => { if (on) { setPage(p); setErr(''); } }).catch((e) => { if (on) setErr(String(e.message || e)); });
    return () => { on = false; };
  }, [win, ui.project]);
  const bar = html`<div class="cw">${WINDOWS.map(([k, t]) => html`<button key=${k} class=${k === win ? 'on' : ''} onClick=${() => setWin(k)}>${t}</button>`)}</div>`;
  if (err) return html`<div class="cost">${bar}<div class="ban bad">${err}</div></div>`;
  if (!page) return html`<div class="cost">${bar}<p class="loading">Loading…</p></div>`;
  if (!page.runs) return html`<div class="cost">${bar}<${EmptyState} title="No runs in this window." body="Runs older than the kept logs are not counted." /></div>`;
  return html`<div class="cost">${bar}
    <p class="csum">${page.runs} run${page.runs === 1 ? '' : 's'} · cost counts only calls whose cost the worker gave; the others are listed as unknown.</p>
    ${GROUPS.map(([k, t]) => html`<${Group} key=${k} title=${t} name=${k} rows=${page[k]} drill=${page.drill} snap=${snap} open=${open} onOpen=${setOpen} />`)}
    ${page.waits.length > 0 && html`<section class="cg"><h3>Waits</h3><table class="ct"><tbody>${page.waits.map((r) => html`<tr key=${r.key}><td>${r.key}</td><td>${dur(r.secs)}</td></tr>`)}</tbody></table></section>`}
  </div>`;
}
