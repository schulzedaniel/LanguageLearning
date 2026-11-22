// Minimal, safe markdown for tutor messages: **target language**, *italic*, ✏️ corrections, lists.
import { escapeHtml } from './ui.js';

function inline(s) {
  let t = escapeHtml(s);
  t = t.replace(/\*\*(.+?)\*\*/g, (_, w) => `<strong class="tl" data-tl="${w.replace(/"/g, '&quot;')}">${w}</strong>`);
  t = t.replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\w)/g, '$1<em>$2</em>');
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  return t;
}

export function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r/g, '').split('\n');
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { closeList(); continue; }
    let t = line.trim();
    const mid = t.indexOf('✏️');
    if (mid > 0) {
      closeList();
      out.push(`<p>${inline(t.slice(0, mid).trim())}</p>`);
      t = t.slice(mid);
    }
    if (/^(>\s*)?✏️/.test(t)) {
      closeList();
      out.push(`<div class="correction">${inline(t.replace(/^>\s*/, ''))}</div>`);
      continue;
    }
    const ul = t.match(/^[-*•]\s+(.*)$/);
    const ol = t.match(/^\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const kind = ul ? 'ul' : 'ol';
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      continue;
    }
    closeList();
    const hm = t.match(/^#{1,4}\s+(.*)$/);
    if (hm) { out.push(`<p><b>${inline(hm[1])}</b></p>`); continue; }
    out.push(`<p>${inline(t.replace(/^>\s*/, ''))}</p>`);
  }
  closeList();
  return out.join('');
}

export function stripMarkdown(text) {
  return String(text || '').replace(/\*\*/g, '').replace(/✏️/g, '').trim();
}
