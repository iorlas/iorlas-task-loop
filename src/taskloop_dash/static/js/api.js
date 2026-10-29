// The server side of the page: /api/v2 (docs/contracts/dash-api-v2.md). Polls the snapshot every 2.5 s while the page is
// visible and at once on focus; sends `since` so an unchanged snapshot is a 304. A failed poll keeps the last data and
// backs off up to 30 s.

const POLL_MS = 2500;
const MAX_BACKOFF_MS = 30000;

export const net = { snap: null, fetchedAt: 0, error: '', failures: 0 };

const subs = new Set();
export const onData = (fn) => (subs.add(fn), () => subs.delete(fn));
const emit = () => subs.forEach((fn) => fn());

let timer = 0;

async function poll() {
  clearTimeout(timer);
  try {
    const q = net.snap ? `?since=${encodeURIComponent(net.snap.version)}` : '';
    const r = await fetch(`/api/v2/snapshot${q}`, { cache: 'no-store' });
    if (r.status === 304) {
      net.fetchedAt = Date.now();
    } else if (r.ok) {
      const snap = await r.json();
      if (net.snap && net.snap.server.version !== snap.server.version) location.reload(); // new server code: new page
      net.snap = snap;
      net.fetchedAt = Date.now();
    } else {
      throw new Error(`HTTP ${r.status}`);
    }
    net.error = '';
    net.failures = 0;
  } catch (e) {
    net.error = String(e.message || e);
    net.failures += 1;
  }
  emit();
  if (!document.hidden) timer = setTimeout(poll, net.failures ? Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** net.failures) : POLL_MS);
}

export function start() {
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  addEventListener('focus', poll);
  poll();
}

export const retry = poll;

// the server's now: Snapshot.t plus the browser time since that fetch (a 304 keeps the old t)
export const now = () => (net.snap ? net.snap.t + (Date.now() - net.fetchedAt) / 1000 : Date.now() / 1000);

// data age in seconds, for the refresh circle and the stale states (§10)
export const dataAge = () => (net.fetchedAt ? (Date.now() - net.fetchedAt) / 1000 : 0);

export async function bead(project, id) {
  const r = await fetch(`/api/v2/bead?project=${encodeURIComponent(project)}&id=${encodeURIComponent(id)}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// POST /api/v2/<verb> with its WRITES record; a refused write is {ok:false, message}, never a throw
export async function write(verb, body) {
  try {
    const r = await fetch(`/api/v2/${verb}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) return { ok: false, message: `${verb} failed: HTTP ${r.status}` };
    const res = await r.json();
    if (res.ok) retry();
    return res;
  } catch (e) {
    return { ok: false, message: `${verb} failed: ${e.message || e}` };
  }
}

const LIVE_WAIT_S = 25, LIVE_MIN_MS = 1000;

// the live tail of a running worker: long-polls /api/v2/live from the cursor and hands each page to onPage until the run
// ends or stop() is called (dash-spec §11.2: no SSE)
export function liveTail(project, id, onPage) {
  let cursor = '', on = true;
  (async () => {
    while (on) {
      const t0 = Date.now();
      try {
        const q = `project=${encodeURIComponent(project)}&id=${encodeURIComponent(id)}&since=${encodeURIComponent(cursor)}&wait=${LIVE_WAIT_S}`;
        const r = await fetch(`/api/v2/live?${q}`, { cache: 'no-store' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const page = await r.json();
        if (!on) return;
        const fresh = page.cursor !== cursor;
        cursor = page.cursor;
        if (fresh) onPage(page);
        if (page.state !== 'live') return;
      } catch (e) {
        if (on) onPage({ error: String(e.message || e) });
        await new Promise((res) => setTimeout(res, MAX_BACKOFF_MS / 3));
      }
      const spent = Date.now() - t0;
      if (spent < LIVE_MIN_MS) await new Promise((res) => setTimeout(res, LIVE_MIN_MS - spent));
    }
  })();
  return () => { on = false; };
}
