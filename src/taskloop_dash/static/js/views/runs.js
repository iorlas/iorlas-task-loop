// Standalone stage runs read from manifests, including work with no bead or loop.
import { html, useState } from '../../vendor/ui-runtime.js';
import { age } from '../format.js';
import { ui } from '../state.js';

function RunRow({ r, now }) {
  const [expanded, expand] = useState(false);
  const summary = `${r.mode} · ${r.project} · ${r.state} · ${age(r.started, now)}`;
  const full = `${summary} · owner: ${r.owner || '—'} · session: ${r.session || '—'}${r.reason ? ` · ${r.reason}` : ''}`;
  return html`<button class=${`run-row ${expanded ? 'expanded' : ''}`} title=${full} aria-expanded=${expanded}
    onClick=${() => expand(!expanded)}>${expanded ? full : `${summary}${r.reason ? ` · ${r.reason}` : ''}`}</button>`;
}

export function Runs({ snap, now }) {
  const runs = [...(snap.runs || [])].sort((a, b) => b.started - a.started).slice(0, 10)
    .filter((r) => ui.project === 'all' || r.project === ui.project);
  if (!runs.length) return null;
  return html`<section class="runs"><h3>Runs</h3><div class="term">
    ${runs.map((r) => html`<${RunRow} key=${r.run} r=${r} now=${now} />`)}
  </div></section>`;
}
