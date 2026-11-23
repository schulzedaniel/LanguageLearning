// Post-session review: feedback, mistakes, unit progress, flashcard candidates → Anki.
import { api, state, LANGS, GENDERS } from '../api.js';
import { h, icon, mount, loading, toast, fmtDate, fmtDuration, progressBar, download, empty, spinner } from '../ui.js';
import { renderMarkdown } from '../markdown.js';
import { navigate, refreshStatusSoon } from '../nav.js';
import { startSession } from './start.js';

export default async function review(main, { id }) {
  mount(main, loading());
  const s = await api.get(`/api/sessions/${id}`);
  const L = LANGS[s.language];
  const a = s.analysis;

  if (!a) {
    mount(main, h('div', { class: 'page' },
      h('div', { class: 'callout warn' }, icon('info'), h('div', {}, 'This session has not been reviewed yet. ',
        h('a', { href: `#/session/${s.id}` }, 'Continue the session'), ' and press "End & review" when you\'re done.'))));
    return;
  }

  const head = h('div', { class: 'page-head' },
    h('div', {},
      h('div', { class: 'row small faint' }, h('span', { class: 'badge accent' }, s.mode_info?.title || s.mode),
        s.unit ? h('span', {}, `${s.unit.level} · ${s.unit.title}`) : null),
      h('h1', { class: 'mt' }, a.title || s.title),
      h('div', { class: 'sub' }, `${fmtDate(s.created_at, { time: true })} · ${fmtDuration(s.duration)} · ${s.messages.filter((m) => m.role === 'user').length} turns`)),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: () => navigate(`session/${s.id}`) }, icon('chat', 16), 'Continue session'),
      h('button', { class: 'btn primary', onclick: () => startSession({ mode: s.mode === 'placement' ? 'lesson' : s.mode, unit_id: null }) }, icon('play', 16), 'New session')));

  // --- feedback ---
  const feedback = h('div', { class: 'card' },
    h('h3', {}, `Feedback from ${L.tutor}`),
    h('p', {}, a.feedback),
    h('div', { class: 'grid c2 mt' },
      h('div', {}, h('div', { class: 'section-label', style: { marginTop: 0 } }, 'What went well'),
        h('div', { class: 'col', style: { gap: '6px' } }, (a.strengths || []).map((x) => h('div', { class: 'goal' }, icon('checkCircle', 15), x)))),
      h('div', {}, h('div', { class: 'section-label', style: { marginTop: 0 } }, 'Practise next'),
        h('div', { class: 'col', style: { gap: '6px' } }, (a.focus_next || []).map((x) => h('div', { class: 'goal' }, icon('target', 15), x))))));

  // --- progress ---
  const progressCards = [];
  if (a.unit_mastery_total !== undefined) {
    progressCards.push(h('div', { class: 'card' },
      h('h3', {}, 'Unit progress'),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, progressBar(a.unit_mastery_total)), h('b', {}, `${Math.round(a.unit_mastery_total * 100)}%`)),
      h('div', { class: 'small faint mt' }, `This session: ${Math.round(a.unit_mastery * 100)}% · ${a.unit_sessions} session(s) on this unit · level estimate ${a.cefr_estimate || '–'}`),
      a.can_do?.length ? h('div', { class: 'mt' }, a.can_do.map((c) => h('div', { class: 'row small', style: { margin: '6px 0' } },
        h('div', { style: { width: '90px' } }, progressBar(c.score, 'thin')), h('span', { class: 'muted' }, c.goal)))) : null,
      a.advance && a.advance.next ? (a.advance.done
        ? h('div', { class: 'callout good mt' }, icon('checkCircle'), h('div', {}, h('b', {}, 'Unit complete! '), `Next up: ${a.advance.next.title}`))
        : h('div', { class: 'callout good mt' }, icon('award'), h('div', { class: 'grow' }, h('b', {}, 'You\'re ready for the next unit. '), a.advance.next.title),
          h('button', { class: 'btn sm primary', onclick: async (e) => { e.target.disabled = true; await api.post(`/api/learner/${s.language}/advance`); toast(`Moved on to "${a.advance.next.title}"`, 'success'); } }, 'Move on')))
        : null));
  }
  if (a.recommended_unit_id) {
    progressCards.push(h('div', { class: 'card' }, h('h3', {}, 'Placement result'),
      h('p', {}, `Estimated level: `, h('b', {}, a.cefr_estimate || '?')),
      h('p', { class: 'muted' }, `Suggested starting unit: ${a.recommended_unit_id}`),
      h('button', { class: 'btn primary', onclick: async () => {
        await api.put(`/api/learner/${s.language}`, { current_unit_id: a.recommended_unit_id, complete_previous: true });
        toast('Starting unit updated', 'success'); navigate('');
      } }, icon('arrowRight', 15), 'Start from this unit')));
  }
  if (a.exam_max > 0) {
    const pct = a.exam_score / a.exam_max;
    progressCards.push(h('div', { class: 'card' }, h('h3', {}, 'Exam simulation score'),
      h('div', { class: 'row gap-lg' }, ring(pct), h('div', {}, h('div', { style: { fontSize: '28px', fontWeight: 750 } }, `${a.exam_score} / ${a.exam_max}`),
        a.exam_max === 9 ? h('div', { class: 'badge accent' }, `IELTS band ${a.exam_score}`)
          : a.exam_max === 6 ? h('div', { class: 'badge accent' }, `TOEFL band ${a.exam_score}`)
          : a.exam_max === 160 ? h('div', { class: 'badge accent' }, `DET score ${a.exam_score}`)
          : h('div', { class: `badge ${pct >= 0.5 ? 'good' : 'warn'}` }, pct >= 0.5 ? 'Pass level' : 'Below pass level (50%)'))),
      a.exam_breakdown ? h('div', { class: 'small muted mt', html: renderMarkdown(a.exam_breakdown) }) : null));
  }

  // --- mistakes ---
  const errors = h('div', { class: 'card' }, h('h3', {}, 'Mistakes to learn from'),
    a.errors?.length ? a.errors.map((e) => h('div', { class: 'err' },
      h('div', { class: 'row wrap small' }, h('span', { class: 'badge' }, e.category), h('b', {}, e.pattern)),
      h('div', {}, h('span', { class: 'wrong' }, e.wrong), '  →  ', h('span', { class: 'right' }, e.right)),
      h('div', { class: 'small muted' }, e.explanation)))
      : h('div', { class: 'muted' }, 'No significant mistakes — great job!'));

  // --- vocab candidates ---
  const vocabCard = h('div', { class: 'card' });
  renderVocab(vocabCard, s);

  // --- memories ---
  const memCard = (a.memories || []).length ? h('div', { class: 'card' },
    h('div', { class: 'card-head' }, h('h3', {}, `New things ${L.tutor} will remember`), h('a', { href: '#/memory', class: 'small' }, 'Manage →')),
    a.memories.map((m) => h('div', { class: 'goal' }, icon('brain', 14), m.content))) : null;

  // --- transcript ---
  const transcript = h('details', { class: 'card' }, h('summary', { style: { cursor: 'pointer', fontWeight: 650 } }, 'Transcript'),
    h('div', { class: 'col mt' }, s.messages.map((m) => h('div', { class: 'small' }, h('b', {}, m.role === 'user' ? 'You: ' : `${L.tutor}: `),
      h('span', { html: renderMarkdown(m.content).replace(/<\/?p>/g, ' ') })))),
    h('div', { class: 'mt' }, h('a', { href: `/api/sessions/${s.id}/export.md`, class: 'btn sm' }, icon('download', 14), 'Export as Markdown')));

  mount(main, h('div', { class: 'page' }, head,
    h('div', { class: 'grid c2' }, h('div', { class: 'col gap-lg' }, feedback, errors), h('div', { class: 'col gap-lg' }, ...progressCards, memCard)),
    h('div', { class: 'mt-lg' }, vocabCard),
    h('div', { class: 'mt-lg' }, transcript)));
}

function ring(frac) {
  const r = 36, c = 2 * Math.PI * r;
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('viewBox', '0 0 86 86'); el.setAttribute('class', 'score-ring');
  el.innerHTML = `<circle cx="43" cy="43" r="${r}" fill="none" stroke="var(--bg-sunk)" stroke-width="9"/>
    <circle cx="43" cy="43" r="${r}" fill="none" stroke="${frac >= 0.5 ? 'var(--good)' : 'var(--warn)'}" stroke-width="9" stroke-linecap="round"
      stroke-dasharray="${c * frac} ${c}" transform="rotate(-90 43 43)"/>
    <text x="43" y="49" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor">${Math.round(frac * 100)}%</text>`;
  return el;
}

function renderVocab(card, s) {
  const lang = s.language;
  const words = s.vocab || [];
  const candidates = words.filter((v) => v.status === 'candidate');
  const done = words.filter((v) => v.status !== 'candidate' && v.status !== 'ignored');
  const ankiOk = state.status?.anki?.ok;
  const selected = new Set(candidates.map((v) => v.id));
  const vErr = s.analysis?.vocab_error;
  const auto = s.analysis?.anki_auto;

  const reasons = { mistake: ['bad', 'you struggled'], asked: ['warn', 'you asked'], unit: ['accent', 'unit word'], new: ['', 'new'] };
  const rows = candidates.map((v) => {
    const cb = h('input', { type: 'checkbox', checked: true, onchange: () => { cb.checked ? selected.add(v.id) : selected.delete(v.id); } });
    const field = (key, ph, w) => h('input', { type: 'text', value: v[key] || '', placeholder: ph, style: w ? { width: w } : null,
      onchange: async (e) => { v[key] = e.target.value; await api.patch(`/api/vocab/${v.id}`, { [key]: e.target.value }); } });
    const genderSel = h('select', { style: { width: '70px', padding: '5px' }, onchange: async (e) => { await api.patch(`/api/vocab/${v.id}`, { gender: e.target.value }); } },
      ['', ...(GENDERS[lang] || [])].map((g) => h('option', { value: g, selected: v.gender === g }, g || '—')));
    const [cls, label] = reasons[v.reason] || reasons.new;
    return h('tr', { class: 'vocab-row' },
      h('td', {}, cb),
      h('td', {}, field('lemma', 'word'), h('div', { class: 'tiny faint mt' }, v.pos, ' ', h('span', { class: `badge ${cls}` }, label))),
      (GENDERS[lang] || []).length ? h('td', {}, genderSel) : null,
      h('td', {}, field('translation', 'translation')),
      h('td', {}, field('example', 'example sentence'), h('div', { style: { marginTop: '4px' } }, field('example_translation', 'translation of the example'))),
      h('td', { class: 'small faint' }, v.forms));
  });

  const act = async (action) => {
    const ids = [...selected];
    if (!ids.length && action !== 'ignore') { toast('Select at least one word', 'error'); return; }
    const toIgnore = candidates.filter((v) => !selected.has(v.id)).map((v) => v.id);
    mount(card, h('div', { class: 'loading-block' }, spinner(), action === 'anki' ? 'Creating cards in Anki (with audio)…' : 'Saving…'));
    try {
      const res = ids.length && action !== 'ignore' ? await api.post('/api/vocab/bulk', { ids, action }) : {};
      if (action === 'ignore') await api.post('/api/vocab/bulk', { ids: candidates.map((v) => v.id), action: 'ignore' });
      else if (toIgnore.length) await api.post('/api/vocab/bulk', { ids: toIgnore, action: 'ignore' });
      if (action === 'anki') {
        if (res.failed?.length) toast(`${res.added.length} cards added, ${res.failed.length} failed: ${res.failed[0].error}`, 'error', 8000);
        else toast(`${res.added.length} cards added to Anki`, 'success');
      } else if (action === 'accept') toast(`${ids.length} words saved`, 'success');
    } catch (e) { toast(e.message, 'error', 7000); }
    const fresh = await api.get(`/api/sessions/${s.id}`);
    s.vocab = fresh.vocab;
    renderVocab(card, s);
    refreshStatusSoon();
  };

  mount(card, 
    h('div', { class: 'card-head' }, h('h3', {}, 'Flashcards from this session'),
      h('span', { class: 'small faint' }, candidates.length ? 'Edit anything before saving. Unchecked words won\'t be suggested again.' : '')),
    vErr ? h('div', { class: 'callout warn mb' }, icon('alert'), `Vocabulary extraction failed: ${vErr}`) : null,
    candidates.length ? h('div', {},
      h('div', { style: { overflowX: 'auto' } }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, 'Word'), (GENDERS[lang] || []).length ? h('th', {}, lang === 'sv' ? 'en/ett' : 'Gender') : null, h('th', {}, lang === 'en' ? 'Definition' : 'Meaning'), h('th', {}, 'Example'), h('th', {}, 'Forms'))),
        h('tbody', {}, rows))),
      h('div', { class: 'row wrap mt' },
        h('button', { class: 'btn primary', disabled: !ankiOk, title: ankiOk ? '' : 'Open Anki (with AnkiConnect) to enable', onclick: () => act('anki') }, icon('cards', 16), 'Add selected to Anki'),
        h('button', { class: 'btn', onclick: () => act('accept') }, icon('check', 16), 'Save without Anki'),
        h('button', { class: 'btn', onclick: () => download('/api/vocab/export.apkg', { ids: [...selected] }, 'parlera.apkg').catch((e) => toast(e.message, 'error')) }, icon('download', 16), 'Download .apkg'),
        h('button', { class: 'btn ghost', onclick: () => act('ignore') }, 'Skip all'),
        !ankiOk ? h('span', { class: 'small faint' }, 'Anki isn\'t open — start Anki to push cards directly.') : null))
      : done.length ? h('div', {},
        auto && auto.added?.length ? h('div', { class: 'callout good mb' }, icon('checkCircle'), h('div', {}, h('b', {}, `${auto.added.length} new card${auto.added.length === 1 ? '' : 's'} added to Anki`),
          ` (deck "${state.settings.anki?.decks?.[lang] || ''}"). Remove any you don't want with ×.`)) : null,
        auto && auto.queued ? h('div', { class: 'callout warn mb' }, icon('info'), h('div', {}, `Anki wasn't open — ${auto.queued} word(s) are queued and will be sent automatically next time Anki is running.`)) : null,
        h('div', { class: 'chips' }, done.map((v) => h('span', { class: 'chip', title: v.example || '' }, h('b', { class: `word-g-${v.gender}` }, v.display || v.lemma),
          h('span', { class: 'm' }, v.translation), v.anki_note_id ? icon('cards', 12) : null,
          h('button', { class: 'btn ghost icon sm', style: { padding: '0 2px' }, title: v.anki_note_id ? 'Remove from Anki' : 'Don\'t learn this word',
            onclick: async () => {
              try {
                if (v.anki_note_id) await api.post('/api/vocab/bulk', { ids: [v.id], action: 'unanki' });
                else await api.post('/api/vocab/bulk', { ids: [v.id], action: 'ignore' });
                toast(`Removed "${v.lemma}"`); const fresh = await api.get(`/api/sessions/${s.id}`); s.vocab = fresh.vocab; renderVocab(card, s);
              } catch (e) { toast(e.message, 'error'); }
            } }, icon('x', 12))))),
      h('div', { class: 'small faint mt' }, 'Manage all words in ', h('a', { href: '#/vocab' }, 'Vocabulary'), '.'))
        : empty('cards', 'No new words this time.'));
}
