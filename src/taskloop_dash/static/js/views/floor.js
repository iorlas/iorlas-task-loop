// Floor (dash-spec §4): one row per slot, grouped by machine, each bead one BeadLine per piece. A comeback in another slot
// is a second piece joined to the first by a dashed curve. Hours back, "now", the hatched future; zoom 2/4/8 h opens on now.
// The phone (§9) shows one card per slot with a 2 h strip instead.
import { html, useEffect } from '../../vendor/ui-runtime.js';
import { causeOf, idx, key, liveSegment, MACHINE_ICON, machineOf, muted, visible } from '../data.js';
import { bid, clock, dur } from '../format.js';
import { set, ui } from '../state.js';
import { EmptyState } from '../ui/kit.js';
import { BeadLine, Strip, useWidth } from '../ui/line.js';
import { openBead } from './shell.js';
import { Runs } from './runs.js';

const BACK_H = 8, AHEAD_H = 2, AXIS = 22, ROW = 46, GRP = 24, LINE_Y = 18;
export const ZOOMS = ['2', '4', '8'];
const TICK = { 2: 900, 4: 1800, 8: 3600 };
export const zoomOf = () => (ZOOMS.includes(ui.opt) ? +ui.opt : 8);

const LEGEND = [['', 'stage'], ['f', 'failed test'], ['live', 'running'], ['park', 'waiting on you'], ['parkx', 'parked'], ['proj', 'planned']];

const tickLabel = (d) => (d < 0 ? `−${d <= -3600 && d % 3600 === 0 ? `${-d / 3600}h` : dur(-d)}` : `+${dur(d)}`);

// slots grouped by machine, in snapshot order; the machine filter hides other machines
function groups(snap) {
  const out = [];
  for (const s of snap.slots) {
    const m = machineOf(s);
    if (ui.machine !== 'all' && m !== ui.machine) continue;
    let g = out.find((x) => x.m === m);
    if (!g) out.push((g = { m, slots: [] }));
    g.slots.push(s);
  }
  return out;
}

function Track({ snap, slot, x, now, beadOf }) {
  const pieces = snap.pieces.filter((p) => p.slot === slot.id && p.segs.length && beadOf(p) && visible(snap, beadOf(p)));
  const busy = pieces.some((p) => p.segs[p.segs.length - 1].t1 >= now - 60 && !['ask', 'answered', 'parked'].includes(p.segs[p.segs.length - 1].kind));
  const idle = (slot.state === 'free' || slot.state === 'idle') && !busy;
  return html`<div class="trk">${pieces.map((p) => {
    const b = beadOf(p), t0 = p.segs[0].t0, t1 = p.segs[p.segs.length - 1].t1;
    return html`<div key=${p.bead + p.n} class="nm" style=${`left:${x(t0)}px;width:${Math.max(2, x(t1) - x(t0))}px`} onClick=${() => openBead(b)}>
        <span>${p.from_slot ? '↪ ' : ''}${bid(p.bead, p.project, ui.project === 'all')} · ${b.title}${b.loops > 0 && html` <small>↻${b.loops}</small>`}${p.from_slot && html` <small>from ${p.from_slot}</small>`}</span></div>
      <${BeadLine} key=${`l${p.bead}${p.n}`} segs=${p.segs} pulse=${liveSegment(snap, p)} x=${x} ack=${muted(b)} cause=${causeOf(b)} sel=${ui.bead === b.id}
        cl=${!!p.from_slot} cr=${!!p.to_slot} capR=${p.to_slot ? `→ ${p.to_slot}` : ''} end=${p.landed ? '✅' : ''} onOpen=${() => openBead(b)} />`;
  })}
    ${idle && html`<div class="idl" style=${`top:${LINE_Y}px;left:${x(now) + 6}px`}>${slot.idle_why || `idle · no ${slot.lane} work ready`}</div>`}
  </div>`;
}

// the dashed curves of comebacks: the end of one piece to the start of the next piece of that bead
function jumps(snap, rows, x) {
  const out = [];
  for (const p of snap.pieces) {
    if (!p.to_slot || rows[p.slot] == null || rows[p.to_slot] == null) continue;
    const q = snap.pieces.find((o) => o.project === p.project && o.bead === p.bead && o.n === p.n + 1);
    if (!q) continue;
    const x1 = x(p.segs[p.segs.length - 1].t1) + 2, y1 = rows[p.slot] + LINE_Y + 11;
    const x2 = x(q.segs[0].t0) - 2, y2 = rows[q.slot] + LINE_Y + 11, mx = (x1 + x2) / 2;
    out.push(html`<path key=${`j${p.bead}${p.n}`} d=${`M${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} /><circle key=${`c${p.bead}${p.n}`} cx=${x2} cy=${y2} r="2.5" />`);
  }
  return out;
}

// a locked lane walls off its slots at now, labelled on the axis row (never over names)
function walls(snap, rows, x, now) {
  return snap.lanes.filter((l) => l.state === 'locked').flatMap((l) => l.slots.filter((s) => rows[s] != null).map((s, i) => html`
    <div key=${l.id + s} class="wall" style=${`left:${x(now)}px;top:${rows[s]}px;height:${ROW}px`}></div>
    ${i === 0 && html`<div key=${`${l.id}h`} class="wall lbl" style=${`left:${x(now)}px;top:0;height:${AXIS}px`}><span>⛔ ${l.name} locked${l.locked_until ? ` until ${clock(l.locked_until)}` : ''}</span></div>`}`));
}

export function Floor({ snap, now, filters }) {
  const [ref, w] = useWidth();
  const zoom = zoomOf();
  const pps = w ? w / ((zoom + 1) * 3600) : 0;
  const t0 = now - BACK_H * 3600, t1 = now + AHEAD_H * 3600;
  const x = (t) => (Math.min(t1, Math.max(t0, t)) - t0) * pps;
  const W = (t1 - t0) * pps;
  const beads = idx(snap).beads;
  const beadOf = (p) => beads.get(key(p.project, p.bead));
  const gs = groups(snap);
  useEffect(() => { if (ref.current && w) ref.current.scrollLeft = x(now + 3600) - w; }, [zoom, !!w]);
  if (!snap.slots.length) return html`<${EmptyState} title="No slots yet." body="Slots appear once the loop runs a worker." cmd="tl loop" /><${Runs} snap=${snap} now=${now} />`;
  const rows = {};
  let H = AXIS;
  const labs = [], trks = [];
  for (const g of gs) {
    labs.push(html`<div key=${`g${g.m}`} class="lab grp">${MACHINE_ICON(g.m)} ${g.m}</div>`);
    trks.push(html`<div key=${`g${g.m}`} class="trk grp"></div>`);
    H += GRP;
    for (const s of g.slots) {
      rows[s.id] = H;
      labs.push(html`<div key=${s.id} class="lab"><b>${s.name}</b><small>${s.lane}</small></div>`);
      if (pps) trks.push(html`<${Track} key=${s.id} snap=${snap} slot=${s} x=${x} now=${now} beadOf=${beadOf} />`);
      H += ROW;
    }
  }
  const ticks = [];
  for (let d = -BACK_H * 3600 + TICK[zoom]; d < AHEAD_H * 3600; d += TICK[zoom]) ticks.push(d);
  return html`<div class="fbar"><span class="seg">${ZOOMS.map((z) => html`<button key=${z} class=${zoom === +z ? 'on' : ''} onClick=${() => set({ opt: z })}>${z} h</button>`)}</span>
      ${filters}<div class="leg">${LEGEND.map(([k, l]) => html`<span key=${l}><i class=${`lg ${k}`}></i>${l}</span>`)}</div></div>
    <div class="fl" style="--lw:120px"><div class="labs"><div class="axh"></div>${labs}</div>
      <div class="sc" ref=${ref}>${pps > 0 && html`<div class="cv" style=${`width:${W + 120}px;height:${H}px`}>
        <div class="axis">${ticks.map((d) => d !== 0 && html`<span key=${d} style=${`left:${x(now + d)}px`}>${tickLabel(d)}</span>`)}</div>
        ${ticks.map((d) => html`<div key=${`gl${d}`} class="gl" style=${`left:${x(now + d)}px`}></div>`)}
        <div class="fut" style=${`left:${x(now)}px;width:${W - x(now)}px`}></div>
        <div class="now" style=${`left:${x(now)}px`}></div>
        <svg class="jmp" width=${W} height=${H}>${jumps(snap, rows, x)}</svg>
        ${walls(snap, rows, x, now)}${trks}</div>`}</div></div><${Runs} snap=${snap} now=${now} />`;
}

// ---- phone: counts, then one card per slot

const PILL = { running: 'live', stuck: 'stuck', look: 'ask', free: '', idle: '', held: '' };

function slotNow(snap, slot) {
  const b = slot.bead ? idx(snap).beads.get(key(slot.project, slot.bead)) : null;
  const pieces = snap.pieces.filter((p) => p.slot === slot.id);
  const mine = b ? pieces.filter((p) => p.bead === b.id && p.project === b.project) : [];
  const piece = mine[mine.length - 1];
  const work = piece ? piece.segs.filter((s) => s.kind !== 'projected') : [];
  return { b, pieces, piece, seg: work[work.length - 1] };
}

function SlotCard({ snap, slot, now }) {
  const { b, pieces, piece, seg } = slotNow(snap, slot);
  const st = slot.state, busy = st === 'running' || st === 'stuck' || st === 'look';
  const pill = st === 'stuck' ? `stuck ${dur(now - (slot.t || now))}` : st === 'look' ? 'your look' : st === 'running' ? 'running' : st === 'held' ? 'held' : 'free';
  let body;
  if (b && busy) {
    const bits = [seg && `${seg.label} · ${dur(now - seg.t0)}`, b.loops > 0 && `↻${b.loops}`, piece && piece.from_slot && `↪ from ${piece.from_slot}`,
      slot.next && `next: ${slot.next}`].filter(Boolean);
    body = html`<div class="t">${b.title}</div><div class="s">${bits.join(' · ')}</div>`;
  } else if (b) {
    body = html`<div class="t">Free · ${bid(b.id, b.project, ui.project === 'all')} parked here</div><div class="s">${slot.idle_why || 'waits on your answer'}</div>`;
  } else {
    body = html`<div class="t">${slot.lane ? `Idle · no ${slot.lane} work ready` : 'Stray claim'}</div>${slot.idle_why && html`<div class="s">${slot.idle_why}</div>`}`;
  }
  const m = machineOf(slot);
  return html`<article class=${`slc ${busy ? '' : 'idle'}`} role=${b ? 'button' : undefined} onClick=${b ? () => openBead(b) : undefined}>
    <div class="h"><b>${MACHINE_ICON(m)} ${slot.name}</b><span>${slot.lane}</span><span class=${`pill ${PILL[st]}`}>${pill}</span></div>
    ${body}<${Strip} pieces=${pieces} pulses=${pieces.map((p) => liveSegment(snap, p))} now=${now} /></article>`;
}

export function PhoneFloor({ snap, now }) {
  const slots = groups(snap).flatMap((g) => g.slots);
  if (!slots.length) return html`<${EmptyState} title="No slots yet." body="Slots appear once the loop runs a worker." /><${Runs} snap=${snap} now=${now} />`;
  const n = (...k) => slots.filter((s) => k.includes(s.state)).length;
  const stat = [['run', n('running'), 'running'], ['x', n('stuck'), 'stuck'], ['you', n('look'), 'your look'], ['mut', n('free', 'idle', 'held'), 'free']];
  return html`<div class="stat">${stat.map(([c, v, l]) => (v > 0 || c === 'run' || c === 'mut') && html`<span key=${l}><i class=${`dt ${c}`}></i>${v} ${l}</span>`)}</div>
    ${slots.map((s) => html`<${SlotCard} key=${s.id} snap=${snap} slot=${s} now=${now} />`)}
    <p class="hint3">Last 2 hours per slot. The full timeline is on the laptop.</p><${Runs} snap=${snap} now=${now} />`;
}
