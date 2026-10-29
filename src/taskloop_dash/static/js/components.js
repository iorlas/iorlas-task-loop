// components.html: every kit component rendered with the real components and the API's data (the fixtures in dev),
// in light, dark and phone (dash-spec §12). Without ?solo the page holds four frames: desktop light and dark, phone light
// and dark (390 px); each frame is this page with ?solo&theme=.
import { html, render, useEffect, useState } from '../vendor/ui-runtime.js';
import { AskCard, LookCard, StickRow, StopActions } from './ui/ask.js';
import { BeadCard, BeadRow, Button, CountBadge, Dots, Drawer, EmptyState, FilterChips, Marker, Meter, MsgLine, Nothing, Panel,
  Popover, Ring, SectionHeader, Sheet, Spark, Status, Tabs, Tag, Toast, Totals } from './ui/kit.js';
import { BeadLine, Strip, Trace } from './ui/line.js';
import { StageCard } from './ui/stage.js';

const q = new URLSearchParams(location.search);
const PHONE = matchMedia('(max-width:600px)').matches;

const TOKENS = ['bg', 'card', 'line', 'cell', 'tx', 'mut', 'ink', 'run', 'runbg', 'red', 'redbg', 'amb', 'ambbg', 'ok', 'okbg', 'you', 'youbg',
  's1', 'stx', 'term', 'termtx', 'v1', 'v2', 'v3', 'v4'];

function Frames() {
  const [h, setH] = useState({});
  useEffect(() => {
    const f = (e) => { if (e.data && e.data.kit) setH((o) => ({ ...o, [e.data.kit]: e.data.h })); };
    addEventListener('message', f);
    return () => removeEventListener('message', f);
  }, []);
  const frames = [['light', 640], ['dark', 640], ['light', 390], ['dark', 390]];
  return html`<div class="kitf">${frames.map(([t, w]) => {
    const id = `${t}-${w}`;
    return html`<figure key=${id}><figcaption>${w === 390 ? 'phone' : 'desktop'} · ${t}</figcaption>
      <iframe title=${id} src=${`?solo=${id}&theme=${t}`} style=${`width:${w}px;height:${h[id] || 600}px`}></iframe></figure>`;
  })}</div>`;
}

function Item({ name, children, note }) {
  return html`<section class="kit-i"><h3>${name}${note && html` <small>${note}</small>`}</h3><div class="kit-b">${children}</div></section>`;
}

const nop = () => {};

function Sheet1({ snap, beads }) {
  const now = snap.t, by = (id) => snap.beads.find((b) => b.id === `lifesim-${id}`);
  const [tab, setTab] = useState('p2');
  const [chip, setChip] = useState('all');
  const pieces = (id) => snap.pieces.filter((p) => p.bead === `lifesim-${id}`);
  const live = beads['6dq0'], stuck = beads['5ban.3'], ask = beads['fld.27'], look = beads['d5f.48'];
  const p0 = Math.min(...snap.pieces.flatMap((p) => p.segs.map((s) => s.t0)));
  const x = (t) => ((t - p0) / (now + 3600 - p0)) * (PHONE ? 330 : 560);
  const frame = (child) => html`<div class="kit-frame">${child}</div>`;
  const soft = snap.asks.find((a) => !a.blocking && a.source === 'ask');
  return html`<div class="kit">
    <${Item} name="Tokens" note="tokens.css only"><div class="sw">${TOKENS.map((t) => html`<span key=${t}><i style=${`background:var(--${t})`}></i>${t}</span>`)}</div><//>
    <${Item} name="Button"><div class="row"><${Button}>⏸ Park<//><${Button} kind="stop">⏹ Stop<//><${Button} kind="pri">Send<//><${Button} disabled>Disabled<//></div><//>
    <${Item} name="FilterChips" note="All first, text only, no counts"><${FilterChips} label="epics" value=${chip} onPick=${setChip}
      items=${snap.epics.filter((e) => e.project === 'lifesim').map((e) => ({ k: e.id, n: e.title, meter: e.total ? e.done / e.total : 0 }))} /><//>
    <${Item} name="Tag"><div class="row">${['', 'run', 'you', 'bad', 'watch', 'ok'].map((t) => html`<${Tag} key=${t} tone=${t}>${t || 'neutral'}<//>`)}</div><//>
    <${Item} name="CountBadge"><div class="tabs"><button class="tab">🏭 Floor<${CountBadge} n=${1} tone="bad" /></button><button class="tab">🙋 Decisions<${CountBadge} n=${3} /></button></div><//>
    <${Item} name="Totals" note="tone from the server; grey under 5 landed"><div class="col">
      ${[['', 12], ['watch', 12], ['bad', 12], ['', 3]].map(([tone, n], i) => html`<div key=${i}><${Totals} totals=${{ secs: 7440 + i * 900, tokens: 400e3 * (i + 1), usual: 500e3, usual_n: n, tone }} assumptions=${i} /></div>`)}</div><//>
    <${Item} name="Tabs" note="one look: 2 px ink underline"><${Tabs} items=${[{ k: 'bead', label: '📄 Bead' }, { k: 'p1', label: '① ↩️' }, { k: 'p2', label: '② now', live: true }]} value=${tab} onPick=${setTab} /><//>
    <${Item} name="Panel + SectionHeader"><${Panel} title="Is the factory learning?" sub="last 8 weeks"><p class="kit-p">Panel body.</p><//>
      <${Panel} title="Ledger" error="ledger: HTTP 500 (this panel only)" /><${SectionHeader} title="Waiting on you" count=${3} /><//>
    <${Item} name="Marker"><div class="row">${['run', 'ask', 'soft_ask', 'parked', 'ready', 'blocked', 'done', 'stuck', 'exited'].map((m) => html`<span key=${m}><${Marker} m=${m} /> ${m}</span>`)}<span><${Marker} goal /> goal</span></div><//>
    <${Item} name="Meter" note="neutral ink, one size"><div class="col">${[0.1, 0.55, 1].map((v) => html`<${Meter} key=${v} v=${v} />`)}</div><//>
    <${Item} name="Dots + Status"><div class="col">${['6dq0', '5ban.3', 'd5f.48'].map((id) => html`<div key=${id}><${Status} card=${by(id)} /><${Dots} dots=${by(id).dots} loops=${by(id).loops} /></div>`)}</div><//>
    <${Item} name="BeadCard"><div class="cards">${['6dq0', '5ban.3', 'fld.27', 'a3k.2', 'q2'].map((id) => html`<${BeadCard} key=${id} card=${by(id)} now=${now} why onOpen=${nop} sel=${id === '6dq0'} />`)}</div><//>
    <${Item} name="BeadRow"><div>${['g1', 'q2', '5ban.3', 'fld.27', '7hv.2'].map((id, i) => html`<${BeadRow} key=${id} card=${by(id)} pad=${i ? 1 : 0} twist=${i ? null : false} onTwist=${nop} onOpen=${nop} />`)}</div><//>
    <${Item} name="BeadLine" note="Floor, comeback pieces"><div class="lines">${snap.pieces.slice(0, 6).map((p, i) => html`<div key=${i} class="trk"><${BeadLine} segs=${p.segs} x=${x} cl=${!!p.from_slot} cr=${!!p.to_slot} capR=${p.to_slot ? `→ ${p.to_slot}` : ''} /></div>`)}</div><//>
    <${Item} name="Trace + Strip"><${Trace} pieces=${pieces('d5f.48')} now=${now} /><${Strip} pieces=${pieces('6dq0')} now=${now} /><//>
    <${Item} name="StageCard" note="pass ② of a 4-pass bead">${look && html`<${StageCard} pass=${look.passes[1]} now=${now} artifacts=${look.artifacts} />`}<//>
    <${Item} name="StageCard, live">${live && html`<${StageCard} pass=${live.passes[live.passes.length - 1]} now=${now} />`}<//>
    <${Item} name="StageCard, stuck">${stuck && html`<${StageCard} pass=${stuck.passes[stuck.passes.length - 1]} now=${now} />`}<//>
    <${Item} name="AskCard">${ask && ask.ask && html`<${AskCard} ask=${ask.ask} now=${now} onPick=${nop} onAskBack=${nop} onCause=${nop} />`}<//>
    <${Item} name="AskCard, not blocking">${soft && html`<${AskCard} ask=${soft} now=${now} onPick=${nop} onAskBack=${nop} onCause=${nop} />`}<//>
    <${Item} name="StickRow" note="after an answer">${ask && ask.ask && html`<${StickRow} ask=${ask.ask} sent=${{ held: 0 }} onStick=${nop} />
      <${StickRow} ask=${ask.ask} sent=${{ held: 4 }} onUndo=${nop} />`}<//>
    <${Item} name="StopActions" note="under a stuck worker">${by('5ban.3') && html`<${StopActions} card=${by('5ban.3')} />`}<//>
    <${Item} name="LookCard">${look && look.ask && html`<${LookCard} ask=${look.ask} now=${now} onApprove=${nop} onSendBack=${nop} />`}<//>
    <${Item} name="Message line">${live && live.passes[live.passes.length - 1].messages.map((m, i) => html`<${MsgLine} key=${i} msg=${m} now=${now} />`)}<//>
    <${Item} name="Drawer" note="contained here">${frame(html`<${Drawer} open modal=${false} onClose=${nop} onWide=${nop}><div class="dh"><div class="l1"><span>lifesim · 6dq0</span></div><h3>Drawer shell</h3></div><//>`)}<//>
    <${Item} name="Sheet" note="phone, contained here">${frame(html`<${Sheet} open modal=${false} title="Filter" onClose=${nop}><p>Sheet body.</p><//>`)}<//>
    <${Item} name="Popover"><${Popover} label="⚠2 problems"><div>same test failed 3×</div><div>tokens 2.8× usual</div><//><//>
    <${Item} name="Toast">${frame(html`<${Toast} modal=${false} toast=${{ text: '✅ Approved · d5f.48 is landing', n: 1 }} />`)}<//>
    <${Item} name="EmptyState"><${EmptyState} title="No beads yet" body="Register a repo, then start its loop." cmd="tl register <repo>  ·  tl run" /><${Nothing} /><//>
    <${Item} name="Ring" note="lanes, refresh circle"><div class="row"><${Ring} v=${0.91} tone="w" value="91%" label="codex" /><${Ring} v=${1} tone="x" value="3d" label="gemini" />
      <${Ring} value="2s" /><${Ring} tone="w" value="41s" /><${Ring} v=${0.62} value="62%" size=${46} /></div><//>
    <${Item} name="Spark"><div class="row">${snap.learning.asks_per_landed.length > 1 && html`<${Spark} v=${snap.learning.asks_per_landed} tone="good" />
      <${Spark} v=${snap.learning.repeat_asks} tone="bad" /><${Spark} v=${snap.learning.sendbacks_per_bead} />`}</div><//>
  </div>`;
}

function Solo() {
  const [st, setSt] = useState(null);
  useEffect(() => {
    (async () => {
      const snap = await (await fetch('/api/snapshot')).json();
      const beads = {};
      for (const id of ['6dq0', '5ban.3', 'fld.27', 'd5f.48']) {
        const b = snap.beads.find((x) => x.id === `lifesim-${id}`);
        if (b) beads[id] = await (await fetch(`/api/bead?project=${b.project}&id=${b.id}`)).json().catch(() => null);
      }
      setSt({ snap, beads });
    })().catch((e) => setSt({ err: String(e) }));
  }, []);
  useEffect(() => {
    let last = 0;
    const root = document.getElementById('root');
    const h = () => {
      const n = root.offsetHeight + 24;
      if (Math.abs(n - last) > 4) { last = n; parent.postMessage({ kit: q.get('solo'), h: n }, '*'); }
    };
    const ro = new ResizeObserver(h);
    ro.observe(root);
    return () => ro.disconnect();
  }, []);
  if (!st) return html`<p class="loading">Loading…</p>`;
  if (st.err) return html`<${EmptyState} title=${`⚠️ ${st.err}`} />`;
  return html`<${Sheet1} snap=${st.snap} beads=${st.beads} />`;
}

document.documentElement.dataset.theme = q.get('theme') || 'light';
document.documentElement.classList.toggle('phone', PHONE);
render(q.has('solo') ? html`<${Solo} />` : html`<${Frames} />`, document.getElementById('root'));
