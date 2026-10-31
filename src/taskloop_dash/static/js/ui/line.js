// BeadLine: the one-line bead (dash-spec §4), cut into phase segments by 1 px inner rules, radius 6 at its outer ends only.
// The Floor, the drawer trace and the phone strip all draw it from Piece.segs.
import { html, useEffect, useRef, useState } from '../../vendor/ui-runtime.js';
import { clock, dur } from '../format.js';

const SEG = { stage: '', failed: 'f', live: 'live', ask: 'park', answered: 'parkx', parked: 'parkx', look: 'wait', stuck: 'stuck', projected: 'proj', wait_slot: 'gap' };
const LINE = { live: 'live', stuck: 'stuck', look: 'wait', ask: 'ask' };

// the outline state of a line: its last segment that is not a forecast
export function lineState(segs, ack) {
  const work = segs.filter((s) => s.kind !== 'projected');
  const last = work.length ? work[work.length - 1].kind : '';
  return `${LINE[last] || ''}${ack ? ' ack' : ''}`;
}

const label = (s, cause) => (s.kind === 'stuck' ? `🛑 stuck · ${cause ? cause.replace('_', ' ') : '?'}` : s.label);

// x maps unix seconds to px; cl/cr square the left/right end where a comeback continues the bead in another slot
export function BeadLine({ segs, x, labels = true, ack, cause, sel, cl, cr, end, capR, onOpen, top, pulse }) {
  if (!segs.length) return null;
  const left = x(segs[0].t0), right = x(segs[segs.length - 1].t1);
  const work = segs.filter((s) => s.kind !== 'projected');
  const wEnd = work.length ? x(work[work.length - 1].t1) : right;
  const st = lineState(segs, ack);
  return html`<div class=${`ln ${st} ${sel ? 'sel' : ''} ${cl ? 'cl' : ''} ${cr ? 'cr' : ''}`} onClick=${onOpen}
      style=${`${top != null ? `top:${top}px;` : ''}left:${left}px;width:${Math.max(2, right - left)}px`}>
    <div class="w">${segs.map((s, i) => {
      const w = Math.max(1, x(s.t1) - x(s.t0)), l = label(s, cause);
      const fits = s.kind === 'wait_slot' ? w > 90 : w > l.length * 5.5 + 8;
      return html`<div key=${i} class=${`sg ${SEG[s.kind]} ${s === pulse ? 'pulse' : ''}`} title=${`${l} · ${dur(s.t1 - s.t0)} · ${clock(s.t0)}–${clock(s.t1)}`}
        style=${`left:${x(s.t0) - left}px;width:${w}px`}>${labels && fits && (s.kind === 'wait_slot' ? html`<span>${l}</span>` : l)}</div>`;
    })}</div>
    <div class="ol" style=${`width:${Math.max(2, wEnd - left)}px`}></div>
    ${end && html`<span class="end" style=${`left:${right - left + 4}px`}>${end}</span>`}
    ${capR && html`<span class="cap" style=${`left:${right - left + 5}px`}>${capR}</span>`}
  </div>`;
}

// the width of an element, kept current
export function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return undefined;
    setW(ref.current.clientWidth); // at once: a ResizeObserver callback waits for a frame
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const ago = (t, now) => (now - t < 60 ? 'now' : `−${dur(now - t)}`);

// the whole bead as one line fitted to the width, ticks at start, middle and now (drawer header, phone bead page)
export function Trace({ pieces, now, ack, cause, labels = true, endMark }) {
  const [ref, w] = useWidth();
  const segs = pieces.flatMap((p) => p.segs).filter((s) => s.kind !== 'projected').sort((a, b) => a.t0 - b.t0);
  if (!segs.length) return html`<div class="trace" ref=${ref}></div>`;
  const t0 = segs[0].t0, t1 = Math.max(segs[segs.length - 1].t1, t0 + 60), room = Math.max(40, w - 22);
  const x = (t) => ((t - t0) / (t1 - t0)) * room;
  const mid = (t0 + t1) / 2;
  return html`<div class="trace" ref=${ref}>${w > 0 && html`
    <${BeadLine} segs=${segs} x=${x} labels=${labels} ack=${ack} cause=${cause} end=${endMark} />
    <span class="tk" style="left:0">${ago(t0, now)}</span>
    <span class="tk mid" style=${`left:${x(mid)}px`}>${ago(mid, now)}</span>
    <span class="tk end" style=${`left:${room}px`}>${ago(t1, now)}</span>`}</div>`;
}

const STRIP = { failed: 'f', stuck: 'stuck', live: 'live', ask: 'park', look: 'wait', answered: 'parkx', parked: 'parkx' };

// the phone's 2 h slot strip in segment colours
export function Strip({ pieces, now, span = 7200, pulses = [] }) {
  const a = now - span, p = (t) => ((Math.max(a, Math.min(now, t)) - a) / span) * 100;
  const segs = pieces.flatMap((x) => x.segs).filter((s) => s.kind !== 'projected' && s.kind !== 'wait_slot' && s.t1 > a && s.t0 < now);
  return html`<div class="stp">${segs.map((s, i) => html`<i key=${i} class=${`${STRIP[s.kind] || ''} ${pulses.includes(s) ? 'pulse' : ''}`} style=${`left:${p(s.t0)}%;width:${p(s.t1) - p(s.t0)}%`}></i>`)}
    <span class="now"></span></div><div class="sax"><span>2 h ago</span><span>1 h</span><span>now</span></div>`;
}
