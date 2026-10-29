// Pure formatting: ages, durations, token counts, bead ids, a small safe markdown. No DOM, no state.

export const MARK = { run: '▶', ask: '🙋', look: '🙋', soft_ask: '⏩', parked: '⏸️', ready: '▷', blocked: '⏳', done: '✅', stuck: '🛑', exited: '💀' };

// tone of a marker for colour classes: you (blue), bad (red), run (teal), '' (grey)
export const MARK_TONE = { run: 'run', ask: 'you', look: 'you', soft_ask: 'you', stuck: 'bad', exited: 'bad' };

export function dur(secs) {
  if (secs == null) return '';
  const s = Math.max(0, Math.round(secs));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60), r = m % 60;
  if (h < 24) return r ? `${h}h${String(r).padStart(2, '0')}` : `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export const age = (t, now) => (t == null ? '' : dur(now - t));

// one unit, rounded: 3d, 5h, 42m (lane rings, dash-spec §8)
export function unit(secs) {
  const s = Math.max(0, secs);
  if (s >= 86400) return `${Math.round(s / 86400)}d`;
  if (s >= 3600) return `${Math.round(s / 3600)}h`;
  return `${Math.max(1, Math.round(s / 60))}m`;
}

// "114k" or "1.2M": a bare number never stands for tokens (dash-spec §6)
export function tokens(n) {
  if (!n) return '0k';
  if (n < 1e6) return `${Math.max(1, Math.round(n / 1000))}k`;
  return `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)}M`;
}

// the bd id as bd prints it, with its project only when All projects is shown (dash-spec §2.1)
// a bead id as shown: bd ids carry their project ("lifesim-4buv"), which the page says once, not twice; the project only
// leads when beads of several projects share the view
let manyProjects = true;
export const setManyProjects = (v) => { manyProjects = v; };
export function bid(id, project, all) {
  const short = id.startsWith(`${project}-`) ? id.slice(project.length + 1) : id;
  return all && manyProjects ? `${project} · ${short}` : short;
}

export const pct = (x) => `${Math.round(x)}%`;

const HM = new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const DAYS = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
export const clock = (t) => HM.format(t * 1000);

// a day label for the ledger: today 10:41, yesterday, N days ago (calendar days, local time)
export function day(t, now) {
  const midnight = (s) => new Date(s * 1000).setHours(0, 0, 0, 0);
  const days = Math.round((midnight(now) - midnight(t)) / 864e5);
  return days <= 0 ? `today ${clock(t)}` : DAYS.format(-days, 'day');
}

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

// markdown subset for helper answers and messages: escaped first, then `code`, **bold**, [n] cites, "- " bullets, paragraphs
export function md(text) {
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  const out = [];
  let list = '';
  const close = () => { if (list) { out.push(`</${list}>`); list = ''; } };
  for (const line of String(text || '').split('\n')) {
    const m = /^\s*(?:([-*])|\d+[.)]) (.*)$/.exec(line);
    if (m) {
      const kind = m[1] ? 'ul' : 'ol';
      if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    close();
    const h = /^#{1,6} (.*)$/.exec(line);
    if (h) out.push(`<h5>${inline(h[1])}</h5>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  close();
  return out.join('');
}
