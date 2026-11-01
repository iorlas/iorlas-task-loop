// The server side of the page: /api (docs/contracts/dash-api.md). Polls the snapshot every 2.5 s while the page is
// visible and at once on focus; sends `since` so an unchanged snapshot is a 304. A failed poll keeps the last data and
// backs off up to 30 s.

import { useEffect, useState } from '../vendor/ui-runtime.js';
import { reconcileProjects } from './state.js';

const POLL_MS = 2500;
const MAX_BACKOFF_MS = 30000;

const store = (url) => ({ url, data: null, fetchedAt: 0, loadedAt: 0, error: '', failures: 0, nextAt: 0, pending: false });
export const net = { ...store('/api/snapshot'), get snap() { return this.data; } };
const resources = new Map();

const subs = new Set();
export const onData = (fn) => (subs.add(fn), () => subs.delete(fn));
const emit = () => subs.forEach((fn) => fn());

let timer = 0;

async function refresh(r) {
  if (document.hidden || r.pending || Date.now() < r.nextAt) return;
  r.pending = true;
  try {
    const q = r.data ? `${r.url.includes('?') ? '&' : '?'}since=${encodeURIComponent(r.data.version)}` : '';
    const res = await fetch(r.url + q, { cache: 'no-store' });
    if (res.status !== 304) {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (r === net && r.data && r.data.server.version !== data.server.version) location.reload();
      r.data = data;
      r.loadedAt = Date.now();
    }
    if (r === net && r.data) reconcileProjects(r.data);
    r.fetchedAt = Date.now();
    r.error = '';
    r.failures = 0;
    r.nextAt = 0;
  } catch (e) {
    r.error = String(e.message || e);
    r.failures += 1;
    r.nextAt = Date.now() + Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** r.failures);
  }
  r.pending = false;
  r.notify?.();
  emit();
}

function poll() {
  clearTimeout(timer);
  if (document.hidden) return;
  [net, ...resources.values()].forEach(refresh);
  timer = setTimeout(poll, POLL_MS);
}

export function start() {
  document.addEventListener('visibilitychange', () => { clearTimeout(timer); if (!document.hidden) poll(); });
  addEventListener('focus', poll);
  poll();
}

export const retry = poll;

// the server's now: Snapshot.t plus the browser time since that fetch (a 304 keeps the old t)
export const now = () => (net.snap ? net.snap.t + (Date.now() - net.loadedAt) / 1000 : Date.now() / 1000);

// data age in seconds, for the refresh circle and the stale states (§10)
export const dataAge = () => (net.fetchedAt ? (Date.now() - net.fetchedAt) / 1000 : 0);

export const resourceAge = (r) => `updated ${Math.floor(r.fetchedAt ? (Date.now() - r.fetchedAt) / 1000 : 0)}s ago`;

// Only mounted resources poll; a revalidation preserves the data, drafts and scroll already on screen.
export function useResource(url) {
  const [state, update] = useState(() => store(url));
  useEffect(() => {
    const r = store(url);
    r.notify = () => update({ ...r });
    resources.set(url, r);
    refresh(r);
    return () => { r.notify = null; resources.delete(url); };
  }, [url]);
  return state;
}

// POST /api/<verb> with its WRITES record; a refused write is {ok:false, message}, never a throw
export async function write(verb, body) {
  try {
    const r = await fetch(`/api/${verb}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Taskloop-Dash': '1' }, body: JSON.stringify(body),
    });
    if (!r.ok) return { ok: false, message: `${verb} failed: HTTP ${r.status}` };
    const res = await r.json();
    if (res.ok) retry();
    return res;
  } catch (e) {
    return { ok: false, message: `${verb} failed: ${e.message || e}` };
  }
}

const LIVE_WAIT_S = 25, LIVE_MIN_MS = 1000;

// the live tail of a running worker: long-polls /api/live from the cursor and hands each page to onPage until the run
// ends or stop() is called (dash-spec §11.2: no SSE)
export function liveTail(project, id, onPage) {
  let cursor = '', on = true;
  (async () => {
    while (on) {
      if (document.hidden) {
        await new Promise((res) => document.addEventListener('visibilitychange', res, { once: true }));
        continue;
      }
      const t0 = Date.now();
      try {
        const q = `project=${encodeURIComponent(project)}&id=${encodeURIComponent(id)}&since=${encodeURIComponent(cursor)}&wait=${LIVE_WAIT_S}`;
        const r = await fetch(`/api/live?${q}`, { cache: 'no-store' });
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
