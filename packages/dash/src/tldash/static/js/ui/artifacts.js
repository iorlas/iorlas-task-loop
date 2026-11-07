// Registered files (tl-jvpm.6): one cell per file, by kind. Images, video, audio and PDF show inline; any other file downloads.
// The bead page's gallery pairs before with after by role (k-th before with k-th after, oldest first); no name is matched.
import { html } from '../../vendor/ui-runtime.js';

const ROLE = { before: 'before', after: 'after', progress: 'progress', result: 'result' };
const where = (a) => (a.stage ? `${a.stage} #${a.attempt}` : '');

export function Media({ a, thumb }) {
  if (a.kind === 'image') return html`<a href=${a.url} target="_blank" rel="noopener"><img src=${a.url} alt=${a.caption || a.name} loading="lazy" /></a>`;
  if (a.kind === 'video') return html`<video src=${a.url} controls preload="metadata" aria-label=${a.caption || a.name}></video>`;
  if (a.kind === 'audio') return html`<audio src=${a.url} controls preload="metadata" aria-label=${a.caption || a.name}></audio>`;
  if (a.kind === 'pdf' && !thumb) return html`<object data=${a.url} type="application/pdf" aria-label=${a.caption || a.name}><a class="file" href=${a.url} target="_blank" rel="noopener">📄 ${a.name}</a></object>`;
  return html`<a class="file" href=${a.url} download=${a.kind === 'file'} target="_blank" rel="noopener">${a.kind === 'pdf' ? '📄' : '📎'} ${a.name}</a>`;
}

function Cell({ a, tag }) {
  return html`<figure class=${`art ${a.kind}`}><${Media} a=${a} /><figcaption>${tag && html`<b>${tag}</b> `}${a.caption || a.name}<small> ${where(a)}</small></figcaption></figure>`;
}

// before/after pairs first (newest pair first), then every other file newest first
export function layout(items) {
  const asc = (role) => items.filter((a) => a.role === role).sort((x, y) => x.t - y.t);
  const before = asc('before'), after = asc('after');
  const pairs = [];
  for (let i = 0; i < Math.max(before.length, after.length); i += 1) pairs.push([before[i], after[i]]);
  const rest = items.filter((a) => a.role !== 'before' && a.role !== 'after').sort((x, y) => y.t - x.t);
  return { pairs: pairs.reverse(), rest };
}

export function ArtifactGallery({ items }) {
  if (!items.length) return null;
  const { pairs, rest } = layout(items);
  return html`<div class="agal">
    ${pairs.map(([b, a], i) => html`<div key=${`p${i}`} class="apair">${b ? html`<${Cell} a=${b} tag=${ROLE.before} />` : html`<figure class="art none">no before</figure>`}
      ${a ? html`<${Cell} a=${a} tag=${ROLE.after} />` : html`<figure class="art none">no after yet</figure>`}</div>`)}
    ${rest.map((a) => html`<${Cell} key=${a.url} a=${a} tag=${a.role !== 'progress' && ROLE[a.role]} />`)}</div>`;
}

// one pass's files on the timeline, grouped by stage attempt: "write #2 · 3 files"
export function AttemptFiles({ items, any }) {
  if (!items.length) return any ? html`<div class="none att">No artifacts in this pass.</div>` : null;
  const groups = [];
  for (const a of [...items].sort((x, y) => x.t - y.t)) {
    const k = where(a);
    const g = groups.find((x) => x.k === k);
    if (g) g.files.push(a); else groups.push({ k, files: [a] });
  }
  return html`<div class="atts">${groups.map((g) => html`<div key=${g.k} class="att"><span class="al">${g.k || 'files'} · ${g.files.length}</span>
    <div class="ath">${g.files.map((a) => html`<figure key=${a.url} class=${`art ${a.kind}`}><${Media} a=${a} thumb /></figure>`)}</div></div>`)}</div>`;
}
