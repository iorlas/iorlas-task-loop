// The bead page: a drawer on desktop, a pushed page on the phone (dash-spec §6). Reads BeadDetail; the live tail of a running
// worker long-polls /api/live into an imperative terminal (spec §12: the terminal tail stays imperative).
import { html, useEffect, useRef, useState } from '../../vendor/ui-runtime.js';
import * as act from '../actions.js';
import * as api from '../api.js';
import { allProjects, causeOf, muted, piecesOf } from '../data.js';
import { age, bid, dur, projectName, tokens } from '../format.js';
import { rememberScroll, scrollOf, set, ui } from '../state.js';
import { AskCard, LookCard, StopActions } from '../ui/ask.js';
import { ArtifactGallery } from '../ui/artifacts.js';
import { BeadRow, EmptyState, Md, MsgLine, Popover, Tabs, Totals } from '../ui/kit.js';
import { Trace } from '../ui/line.js';
import { END, passNum, StageCard } from '../ui/stage.js';
import { Controls, PhoneControls } from './controls.js';
import { BdBanner } from './shell.js';

const TERM_LINES = 10, EXIT_LINES = 20;
const TONE = { err: 'e', ok: 'o', dim: 'd', warn: 'w' };

// the terminal tail: lines appended to the DOM as they come, new ones fade in; Preact never re-renders its content
function Terminal({ card, keep = TERM_LINES, onTools }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    return api.liveTail(card.project, card.id, (page) => {
      if (page.error) return;
      if (page.reset) el.replaceChildren();
      el.dataset.state = page.state;
      if (page.gap) page.lines.unshift({ t: page.lines.length ? page.lines[0].t : Date.now() / 1000, tone: 'warn', text: 'lines before this were removed by retention' });
      for (const l of page.lines) {
        const row = document.createElement('button');
        row.className = `run-row new ${TONE[l.tone] || ''}`;
        row.textContent = row.title = l.text;
        row.dataset.t = l.t;
        row.setAttribute('aria-expanded', 'false');
        row.onclick = () => row.setAttribute('aria-expanded', String(row.classList.toggle('expanded')));
        el.prepend(row);
      }
      [...el.children].sort((a, b) => +b.dataset.t - +a.dataset.t).forEach((r) => el.appendChild(r));
      while (el.childElementCount > keep) el.lastElementChild.remove();
      if (onTools && page.tools.length) onTools((t) => [...t, ...page.tools]);
    });
  }, [card.project, card.id, keep]);
  return html`<div class="term mini" ref=${ref}></div>`;
}

const TOOL_ICON = [[/edit|write|patch/i, '📝'], [/read|view|open/i, '📄'], [/grep|glob|search|find/i, '🔍'], [/bash|shell|exec|run/i, '⌨️']];
const toolIcon = (name) => (TOOL_ICON.find(([re]) => re.test(name)) || [null, '·'])[1];

function ToolCalls({ tools }) {
  if (!tools.length) return null;
  return html`<${Popover} cls="lnk" label=${`${tools.length} tool call${tools.length === 1 ? '' : 's'}`}>
    <div class="calls">${tools.map((t, i) => html`<div key=${i}>${toolIcon(t.name)} <b>${t.name}</b> ${t.arg}</div>`)}</div></${Popover}>`;
}

function RunBox({ d, now }) {
  const lv = d.live;
  const [tools, setTools] = useState([]);
  return html`<div class="box run"><div class="bh">▶ ${lv.phase} · pass ${passNum(lv.pass_n)}<span class="t">${dur(now - lv.t)}</span></div>
    <div class="nm2">${lv.cmd && html`<span class="lb">running</span><span><code>${lv.cmd}</code></span>`}
      <span class="lb">tokens</span><span>${tokens(lv.tokens)} this stage</span>
      ${lv.checks && html`<span class="lb">tests</span><span>${lv.checks.passed}/${lv.checks.total} passed${lv.checks.failed ? html` · <b class="bad">${lv.checks.failed} failed</b>` : ''}${lv.checks.unverified ? html` · <b class="unv">${lv.checks.unverified} unverified</b>` : ''}</span>`}
      <span class="lb">calls</span><span><${ToolCalls} tools=${tools} />${!tools.length && '—'}</span></div>
    <${Terminal} card=${d.card} onTools=${setTools} />
    ${lv.subtasks.length > 0 && html`<ul class="subs">${lv.subtasks.map((s, i) => html`<li key=${i} class=${s.done ? 'done' : ''}>${s.done ? '☑' : '☐'} ${s.text}</li>`)}</ul>`}
  </div>`;
}

// stuck or exited: what happened, since when, the last command, the tail; the cause chips and actions are handed in
function TroubleBox({ d, now, children }) {
  const lv = d.live, exited = lv.kind === 'exited';
  return html`<div class="box bad"><div class="bh">${exited ? `💀 Worker exited${lv.exit_code != null ? ` · code ${lv.exit_code}` : ''}` : '🛑 Stuck'}${lv.why ? ` · ${lv.why}` : ''}
      <span class="t">${age(lv.t, now)} ago</span></div>
    <div class="nm2">${lv.cmd && html`<span class="lb">last</span><span><code>${lv.cmd}</code></span>`}
      ${lv.silent_secs != null && html`<span class="lb">watcher</span><span>no commits, no tool calls for ${dur(lv.silent_secs)}</span>`}
      ${lv.checks && html`<span class="lb">tests</span><span>${lv.checks.passed}/${lv.checks.total} passed · ${lv.checks.failed} failed${lv.checks.unverified ? html` · <b class="unv">${lv.checks.unverified} unverified</b>` : ''}</span>`}</div>
    <${Terminal} card=${d.card} keep=${EXIT_LINES} />${children}</div>`;
}

// the live box of the live pass: run, stuck, exited, an ask or a look (§6)
export function LiveBox({ d, now, hooks = {} }) {
  if (d.ask) {
    return d.ask.source === 'look' ? html`<${LookCard} ask=${d.ask} now=${now} ...${hooks.look || {}} />`
      : html`<${AskCard} ask=${d.ask} now=${now} ...${hooks.ask || {}} />`;
  }
  if (!d.live) return null;
  if (d.live.kind === 'run') return html`<${RunBox} d=${d} now=${now} />`;
  return html`<${TroubleBox} d=${d} now=${now}>${hooks.trouble}</${TroubleBox}>`;
}

const passLabel = (p, d, last) => `${passNum(p.n)} ${last && d.live && d.live.kind === 'run' ? 'now' : END[p.end] || (last ? 'now' : '')}`;

// a blocking ask, a look or a stuck bead opens on the live pass; otherwise the last pass (§6)
export const defaultTab = (d) => (d.passes.length ? `p${d.passes[d.passes.length - 1].n}` : 'bead');

function BeadTab({ d, snap, now }) {
  const all = allProjects();
  const row = (id) => {
    const b = snap.beads.find((x) => x.id === id && x.project === d.card.project);
    return b ? html`<${BeadRow} key=${id} card=${b} all=${all} onOpen=${(x) => set({ bead: x.id, dtab: '' })} />` : html`<div key=${id} class="tr done"><span class="id">${id}</span></div>`;
  };
  return html`<div class="bead">
    ${d.artifacts.length > 0 && html`<h4>Artifacts · ${d.artifacts.length}</h4><${ArtifactGallery} items=${d.artifacts} />`}
    <h4>Description</h4>${d.description ? html`<${Md} text=${d.description} cls="desc" />` : html`<p>—</p>`}
    <h4>Acceptance</h4>${d.acceptance ? html`<${Md} text=${d.acceptance} cls="desc" />` : html`<p>—</p>`}
    ${d.waits_for.length > 0 && html`<h4>Waits for</h4>${d.waits_for.map(row)}`}
    ${d.unblocks.length > 0 && html`<h4>Unblocks</h4>${d.unblocks.map(row)}`}
    ${d.decisions.length > 0 && html`<h4>Slow or rerouted · ${d.decisions.length}</h4>${d.decisions.map((m, i) => html`<${MsgLine} key=${i} msg=${m} now=${now} />`)}`}
    <h4>Comments · ${d.comments.length}</h4>${d.comments.map((m, i) => html`<${MsgLine} key=${i} msg=${m} now=${now} />`)}
  </div>`;
}

function Body({ d, card, snap, now, phone }) {
  const hooks = { ...(d.ask ? act.hooks(d.ask) : {}), trouble: html`<${StopActions} card=${card} />` };
  const tab = ui.dtab || defaultTab(d);
  const last = d.passes.length ? d.passes[d.passes.length - 1].n : 0;
  const items = [{ k: 'bead', label: '📄 Bead' }, ...d.passes.map((p) => ({ k: `p${p.n}`, label: passLabel(p, d, p.n === last), live: p.n === last && d.live && d.live.kind === 'run' }))];
  const pass = d.passes.find((p) => `p${p.n}` === tab);
  const livePhase = d.live ? d.live.phase : null;
  return html`<${Tabs} cls=${phone ? 'ptabs' : 'tabs'} items=${items} value=${pass ? tab : 'bead'} onPick=${(k) => set({ dtab: k })} />
    ${pass ? html`<${StageCard} key=${pass.n} pass=${pass} now=${now} artifacts=${d.artifacts} livePhase=${pass.n === last ? livePhase : null}
        live=${pass.n === last && html`<${LiveBox} d=${d} now=${now} hooks=${hooks} />`} />`
      : html`<${BeadTab} d=${d} snap=${snap} now=${now} />`}`;
}

function Header({ card, d, snap, phone }) {
  const epic = card.epic ? snap.epics.find((e) => e.id === card.epic) : null;
  const meta = [projectName(card.project), epic && epic.title, card.id, card.slot, card.account, card.review && `review: ${card.review}`].filter(Boolean).join(' · ');
  const tot = html`<${Totals} totals=${card.totals} assumptions=${card.assumptions} />`;
  if (phone) return html`<h2>${card.title}</h2><div class="mt">${meta}</div><div class="mt">${tot}${card.loops > 0 && ` · ↻${card.loops}`}</div>`;
  return html`<div class="l1"><span>${meta}</span>${tot}</div><h3>${card.title}</h3>`;
}

// the drawer body scroll survives a refresh (dash-spec §13)
function useBodyScroll(ref, place, ready) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !ready) return undefined;
    el.scrollTop = scrollOf(place);
    const f = () => rememberScroll(place, el.scrollTop);
    el.addEventListener('scroll', f, { passive: true });
    return () => el.removeEventListener('scroll', f);
  }, [place, ready]);
}

export function BeadPage({ snap, card, now, phone }) {
  const resource = api.useResource(`/api/bead?project=${encodeURIComponent(card.project)}&id=${encodeURIComponent(card.id)}`);
  const { data: d, error: err } = resource;
  const scroller = useRef(null);
  useBodyScroll(scroller, `db:${card.project}/${card.id}`, !!d);
  const pieces = piecesOf(snap, card);
  const trace = html`<${Trace} pieces=${pieces} now=${now} ack=${muted(card)} cause=${causeOf(card)} labels=${!phone}
    endMark=${card.column === 'done' ? '✅' : ''} />`;
  const status = html`<div class="data-age">${d && api.resourceAge(resource)}${err && ` · ${err}`}</div>`;
  const body = err && !d ? html`<${EmptyState} title=${`⚠️ ${err}`} body="The bead could not be read; the board keeps working." />`
    : d ? html`<${BdBanner} source=${d} project=${projectName(card.project)} now=${now} />
      <${Body} d=${d} card=${card} snap=${snap} now=${now} phone=${phone} />` : html`<p class="loading">Loading…</p>`;
  if (!phone) {
    return html`<div class="dh"><${Header} card=${card} d=${d} snap=${snap} />${status}${trace}</div>
      <div class="db" ref=${scroller}>${body}</div><${Controls} key=${card.project + card.id} card=${card} />`;
  }
  return html`<div class="pgh"><button class="bk" onClick=${() => history.back()}>‹ Back</button><span class="id">${bid(card.id, card.project, allProjects())}</span><span></span></div>
    <div class="pgb" ref=${scroller}><${Header} card=${card} d=${d} snap=${snap} phone />${status}${trace}${body}</div><${PhoneControls} snap=${snap} card=${card} />`;
}
