// Standalone stage runs read from manifests, including work with no bead or loop.
import { html } from '../../vendor/ui-runtime.js';
import { ui } from '../state.js';

export function RunHeaders({ snap }) {
  const runs = (snap.runs || []).filter((r) => ui.project === 'all' || r.project === ui.project);
  return runs.map((r) => html`<header key=${r.run} class="ban" title=${r.run}>
    <b>${r.mode}</b> · ${r.project} · ${r.state} · owner: ${r.owner || '—'} · session: ${r.session || '—'}
    ${r.reason && html`<span> · ${r.reason}</span>`}
  </header>`);
}
