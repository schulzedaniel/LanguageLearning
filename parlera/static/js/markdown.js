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

// Full Markdown documents (prompt previews, long texts): headings, nested lists, quotes, tables, rules.
// Bold is plain <strong> here, not the clickable target-language style.
function docInline(s) {
  let t = escapeHtml(s);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\w)/g, '$1<em>$2</em>');
  t = t.replace(/~~(.+?)~~/g, '<del>$1</del>');
  return t;
}

export function renderDocument(text) {
  const lines = String(text || '').replace(/\r/g, '').replace(/\t/g, '    ').split('\n');
  const out = [];
  let para = [];
  const stack = [];           // open lists: { kind, indent }
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(docInline).join('<br>')}</p>`); para = []; } };
  const closeLists = (indent = -1) => {
    while (stack.length && stack.at(-1).indent > indent) out.push(`</li></${stack.pop().kind}>`);
  };
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); continue; }
    const indent = line.length - line.trimStart().length;
    const t = line.trim();
    const li = t.match(/^([-*•+]|\d+[.)])\s+(.*)$/);
    if (li) {
      flushPara();
      const kind = /\d/.test(li[1]) ? 'ol' : 'ul';
      closeLists(indent);
      const top = stack.at(-1);
      if (top && top.indent === indent && top.kind === kind) out.push('</li><li>');
      else {
        if (top && top.indent === indent) { out.push(`</li></${stack.pop().kind}>`); }
        out.push(`<${kind}><li>`); stack.push({ kind, indent });
      }
      out.push(docInline(li[2]));
      continue;
    }
    if (stack.length && indent > stack.at(-1).indent) { out.push(' ' + docInline(t)); continue; } // continuation of a list item
    closeLists();
    const hm = t.match(/^(#{1,6})\s+(.*)$/);
    if (hm) { flushPara(); const n = Math.min(6, hm[1].length + 1); out.push(`<h${n} class="md-h">${docInline(hm[2])}</h${n}>`); continue; }
    if (/^(-{3,}|\*{3,}|_{3,}|={3,})$/.test(t)) { flushPara(); out.push('<hr>'); continue; }
    if (t.startsWith('>')) { flushPara(); out.push(`<blockquote>${docInline(t.replace(/^>\s?/, ''))}</blockquote>`); continue; }
    if (t.startsWith('|') && lines[i + 1]?.trim().match(/^\|?\s*:?-{2,}/)) {
      flushPara();
      const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => docInline(c.trim()));
      const head = cells(t);
      i += 1;
      const rows = [];
      while (lines[i + 1]?.trim().startsWith('|')) { i += 1; rows.push(cells(lines[i])); }
      out.push(`<table class="md-table"><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    para.push(t);
  }
  flushPara();
  closeLists();
  return out.join('');
}
