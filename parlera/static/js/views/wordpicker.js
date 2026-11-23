// Review page: the transcript with every word clickable, to pick your own flashcards.
// Highlights: words suggested for this session (and unit words you don't have yet), and words you already have.
// Select several words with the mouse to pick a whole phrase.
import { api, LANGS } from '../api.js';
import { h, icon, mount, toast, spinner } from '../ui.js';

const fold = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[’]/g, "'");
const WORD = /([\p{L}\p{M}][\p{L}\p{M}'’-]*)/u;
const ARTICLES = /^(en|ett|att|le|la|les|un|une|des|l'|the|a|an|to)\s+/i;

// does a transcript token look like a form of this lemma? (bil → bilen, springa → springer, maison → maisons)
function matcher(lemmas) {
  const singles = [];
  for (const raw of lemmas) {
    const l = fold(String(raw).replace(ARTICLES, '')).trim();
    if (!l || l.includes(' ')) continue;
    // drop a typical ending (heta → het-er, springa → spring-er, trevlig → trevlig-t); keep at least 3 letters
    singles.push({ l, stem: l.length <= 3 ? l : l.slice(0, Math.max(3, l.length - (l.length >= 6 ? 2 : 1))) });
  }
  return (token) => {
    const t = fold(token);
    return singles.some(({ l, stem }) => t === l || (l.length >= 4 && t.startsWith(stem) && t.length - l.length <= 4) || (l.length === 3 && t.startsWith(l) && t.length - 3 <= 2));
  };
}

export function transcriptPicker(s, { onAdded } = {}) {
  const lang = s.language;
  const L = LANGS[lang];
  const pending = (s.vocab || []).filter((v) => v.status === 'candidate').map((v) => v.lemma);
  const savedLemmas = (s.saved_lemmas || []).filter((v) => v.status !== 'candidate').map((v) => v.lemma);
  const unitWords = (s.unit?.vocab_pairs || []).map((p) => p.term);
  const isSaved = matcher(savedLemmas);
  const isSuggested = matcher([...pending, ...unitWords]);
  const picked = new Map();   // text → context

  const tray = h('div', { class: 'pick-tray' });
  const renderTray = () => {
    const items = [...picked.keys()];
    mount(tray, items.length
      ? [h('div', { class: 'chips grow' }, items.map((t) => h('span', { class: 'chip tl' }, t,
          h('button', { class: 'btn ghost icon sm', style: { padding: '0 2px' }, title: 'Remove', onclick: () => toggle(t) }, icon('x', 12))))),
        h('button', { class: 'btn ghost sm', onclick: () => { picked.clear(); body.querySelectorAll('.w.picked').forEach((e) => e.classList.remove('picked')); renderTray(); } }, 'Clear'),
        h('button', { class: 'btn primary', onclick: create }, icon('cards', 15), `Create ${items.length} flashcard${items.length === 1 ? '' : 's'}`)]
      : h('div', { class: 'small muted' }, 'Click words in the transcript to pick them (select several words with the mouse for a phrase).'));
  };

  function toggle(text, context = '') {
    const key = text.trim();
    if (picked.has(key)) picked.delete(key); else picked.set(key, context);
    body.querySelectorAll('.w').forEach((e) => { if (e.dataset.w === key) e.classList.toggle('picked', picked.has(key)); });
    renderTray();
  }

  async function create() {
    const words = [...picked.entries()].map(([text, context]) => ({ text, context }));
    mount(tray, h('div', { class: 'row small muted' }, spinner(), ` Filling in meaning, ${lang === 'sv' ? 'en/ett, ' : lang === 'fr' ? 'gender, ' : ''}forms and an example for ${words.length} word${words.length === 1 ? '' : 's'}…`));
    try {
      const r = await api.post(`/api/sessions/${s.id}/pick`, { words });
      picked.clear();
      body.querySelectorAll('.w.picked').forEach((e) => e.classList.remove('picked'));
      const msg = [r.added.length ? `${r.added.length} flashcard${r.added.length === 1 ? '' : 's'} ready to check above` : null,
        r.existing.length ? `already in your words: ${r.existing.map((v) => v.lemma).join(', ')}` : null].filter(Boolean).join(' · ');
      toast(msg || 'Nothing new to add', r.added.length ? 'success' : 'info', 6000);
      renderTray();
      onAdded && onAdded(r);
    } catch (e) { toast(e.message, 'error', 7000); renderTray(); }
  }

  // sentence around a word, for context
  const sentenceOf = (text, word) => (text.split(/(?<=[.!?])\s+/).find((x) => x.includes(word)) || text).slice(0, 300);

  function renderMessage(m) {
    const plain = m.content.replace(/\*\*/g, '');
    const line = h('div', { class: `pick-line ${m.role}` }, h('b', { class: 'who' }, m.role === 'user' ? 'You' : L.tutor));
    const text = h('span', { class: 'pick-text' });
    // keep bold (= target language in the teacher's text) as a visual hint
    String(m.content).split(/(\*\*[^*]+\*\*)/).forEach((seg) => {
      const bold = /^\*\*[^*]+\*\*$/.test(seg);
      const raw = bold ? seg.slice(2, -2) : seg;
      raw.split(WORD).forEach((part, i) => {
        if (i % 2 === 0) { if (part) text.append(document.createTextNode(part)); return; }
        const cls = ['w', bold || m.role === 'user' ? 'target' : '', isSaved(part) ? 'saved' : isSuggested(part) ? 'sugg' : ''].filter(Boolean).join(' ');
        text.append(h('span', { class: cls, 'data-w': part, title: isSaved(part) ? 'Already in your words' : isSuggested(part) ? 'Suggested' : '',
          onclick: () => { if (!window.getSelection()?.toString().trim()) toggle(part, sentenceOf(plain, part)); } }, part));
      });
    });
    line.append(text);
    return line;
  }

  const body = h('div', { class: 'pick-body' }, s.messages.map(renderMessage));
  // select several words → pick the phrase
  body.addEventListener('mouseup', () => setTimeout(() => {
    const sel = window.getSelection();
    const phrase = sel?.toString().replace(/\s+/g, ' ').trim().replace(/^[.,!?;:"«»“”()]+|[.,!?;:"«»“”()]+$/g, '');
    if (!phrase || !phrase.includes(' ') || phrase.split(' ').length > 6 || !body.contains(sel.anchorNode)) return;
    const lineText = (sel.anchorNode.parentElement?.closest('.pick-text')?.textContent) || '';
    sel.removeAllRanges();
    toggle(phrase, sentenceOf(lineText, phrase));
  }, 10));
  renderTray();

  return h('div', { class: 'card', id: 'transcript-picker' },
    h('div', { class: 'card-head' }, h('h3', {}, 'Transcript'),
      h('a', { href: `/api/sessions/${s.id}/export.md`, class: 'btn ghost sm' }, icon('download', 14), 'Export')),
    h('div', { class: 'row wrap small muted mb' }, h('span', {}, 'Make your own flashcards: click any word, or select a phrase.'),
      h('span', { class: 'legend' }, h('span', { class: 'w sugg' }, 'suggested'), ' ', h('span', { class: 'w saved' }, 'already saved'), ' ', h('span', { class: 'w picked' }, 'picked'))),
    body, tray);
}
