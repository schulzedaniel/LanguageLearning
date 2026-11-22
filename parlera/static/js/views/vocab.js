// Vocabulary manager + shared "add word" dialog.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, modal, confirmDialog, fmtDate, download, empty, debounce, spinner } from '../ui.js';

const STATUS = [
  ['', 'All'], ['learning', 'Learning'], ['known', 'Known'], ['candidate', 'Suggested'], ['ignored', 'Skipped'],
];

export default async function vocab(main) {
  const lang = state.language;
  let status = '';
  let q = '';
  const selected = new Set();
  mount(main, loading());

  const tableWrap = h('div');
  const tabs = h('div', { class: 'tabs' });
  const search = h('input', { type: 'search', placeholder: 'Search words, meanings, examples…', style: { maxWidth: '320px' } });
  search.addEventListener('input', debounce(() => { q = search.value.trim(); load(); }, 250));

  const bulkBar = h('div', { class: 'row wrap' });

  async function load() {
    const all = await api.get(`/api/vocab?language=${lang}`);
    const counts = Object.fromEntries(STATUS.map(([k]) => [k, k ? all.filter((v) => v.status === k).length : all.length]));
    mount(tabs, ...STATUS.map(([k, label]) => h('button', { class: status === k ? 'active' : '', onclick: () => { status = k; selected.clear(); load(); } },
      label, h('span', { class: 'count' }, counts[k]))));
    let rows = status ? all.filter((v) => v.status === status) : all;
    if (q) {
      const ql = q.toLowerCase();
      rows = rows.filter((v) => [v.lemma, v.translation, v.example].some((x) => (x || '').toLowerCase().includes(ql)));
    }
    renderTable(rows);
    renderBulk();
  }

  function renderBulk() {
    const n = selected.size;
    const ankiOk = state.status?.anki?.ok;
    mount(bulkBar, 
      h('span', { class: 'small faint' }, n ? `${n} selected` : 'Select words for bulk actions'),
      h('button', { class: 'btn sm', disabled: !n || !ankiOk, title: ankiOk ? '' : 'Anki is not open', onclick: () => bulk('anki') }, icon('cards', 14), 'Send to Anki'),
      h('button', { class: 'btn sm', disabled: !n, onclick: () => bulk('known') }, icon('check', 14), 'Mark known'),
      h('button', { class: 'btn sm', disabled: !n, onclick: () => bulk('accept') }, 'Mark learning'),
      h('button', { class: 'btn sm', disabled: !n, onclick: () => download('/api/vocab/export.apkg', { ids: [...selected] }, 'parlera.apkg').catch((e) => toast(e.message, 'error')) }, icon('download', 14), '.apkg'),
      h('button', { class: 'btn sm danger', disabled: !n, onclick: async () => { if (await confirmDialog(`Delete ${n} word(s)? Cards already in Anki stay there.`, { danger: true, ok: 'Delete' })) bulk('delete'); } }, icon('trash', 14), 'Delete'));
  }

  async function bulk(action) {
    try {
      const r = await api.post('/api/vocab/bulk', { ids: [...selected], action });
      if (action === 'anki') toast(`${r.added?.length || 0} added to Anki${r.failed?.length ? `, ${r.failed.length} failed (${r.failed[0].error})` : ''}`, r.failed?.length ? 'error' : 'success', 6000);
      selected.clear();
      load();
    } catch (e) { toast(e.message, 'error'); }
  }

  function renderTable(rows) {
    if (!rows.length) {
      mount(tableWrap, empty('cards', q ? 'No matches.' : 'No words here yet. They\'ll appear after you review a session, or add your own.'));
      return;
    }
    const all = h('input', { type: 'checkbox', checked: rows.every((r) => selected.has(r.id)), onchange: (e) => { rows.forEach((r) => e.target.checked ? selected.add(r.id) : selected.delete(r.id)); renderTable(rows); renderBulk(); } });
    mount(tableWrap, h('div', { class: 'card', style: { padding: '6px 10px', overflowX: 'auto' } }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, h('th', {}, all), h('th', {}, 'Word'), h('th', {}, 'Meaning'), h('th', {}, 'Example'), h('th', {}, 'Status'), h('th', {}, 'Anki'), h('th', {}, ''))),
      h('tbody', {}, rows.map((v) => h('tr', {},
        h('td', {}, h('input', { type: 'checkbox', checked: selected.has(v.id), onchange: (e) => { e.target.checked ? selected.add(v.id) : selected.delete(v.id); renderBulk(); } })),
        h('td', {}, h('b', { class: `word-g-${v.gender}` }, v.display), v.forms ? h('div', { class: 'tiny faint' }, v.forms) : null, v.pos ? h('div', { class: 'tiny faint' }, v.pos) : null),
        h('td', {}, v.translation),
        h('td', { class: 'small' }, v.example, v.example_translation ? h('div', { class: 'faint' }, v.example_translation) : null),
        h('td', {}, statusBadge(v.status)),
        h('td', { class: 'small' }, v.anki_note_id ? h('span', { title: `Interval ${v.anki_interval ?? '?'} days, lapses ${v.anki_lapses ?? 0}` }, icon('cards', 13), v.anki_interval != null ? ` ${v.anki_interval}d` : ' ✓') : h('span', { class: 'faint' }, '—')),
        h('td', { class: 'actions' },
          h('button', { class: 'btn ghost icon sm', title: 'Edit', onclick: () => editWord(v, load) }, icon('edit', 15)),
          h('button', { class: 'btn ghost icon sm', title: 'Delete', onclick: async () => { if (await confirmDialog(`Delete "${v.lemma}"?`, { danger: true, ok: 'Delete' })) { await api.del(`/api/vocab/${v.id}`); load(); } } }, icon('trash', 15)))))))));
  }

  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Vocabulary'), h('div', { class: 'sub' }, `Your ${LANGS[lang].name} words. Cards are created in Anki; review data flows back to guide your sessions.`)),
      h('div', { class: 'row wrap' },
        h('button', { class: 'btn', onclick: async (e) => {
          const btn = e.currentTarget;
          btn.disabled = true;
          try { const r = await api.post('/api/anki/sync', { language: lang }); toast(`Synced ${r.updated} cards from Anki (${r.known} known)`, 'success'); load(); }
          catch (err) { toast(err.message, 'error'); } finally { btn.disabled = false; }
        } }, icon('refresh', 16), 'Sync from Anki'),
        h('a', { class: 'btn', href: `/api/vocab/export.csv?language=${lang}` }, icon('download', 16), 'CSV'),
        h('button', { class: 'btn primary', onclick: () => addWordDialog(lang, '', '', null, load) }, icon('plus', 16), 'Add word'))),
    h('div', { class: 'row between wrap mb' }, search, bulkBar),
    tabs, tableWrap));
  load();
}

function statusBadge(s) {
  const map = { learning: ['accent', 'learning'], known: ['good', 'known'], candidate: ['warn', 'suggested'], ignored: ['', 'skipped'] };
  const [cls, label] = map[s] || ['', s];
  return h('span', { class: `badge ${cls}` }, label);
}

function wordForm(lang, v) {
  const f = {};
  const input = (key, label, ph = '') => { f[key] = h('input', { type: 'text', value: v[key] || '', placeholder: ph }); return h('label', { class: 'field' }, label, f[key]); };
  f.gender = h('select', {}, ['', ...(lang === 'sv' ? ['en', 'ett'] : ['m', 'f'])].map((g) => h('option', { value: g, selected: (v.gender || '') === g }, g || '—')));
  f.pos = h('select', {}, ['', 'noun', 'verb', 'adjective', 'adverb', 'phrase', 'preposition', 'pronoun', 'conjunction', 'other'].map((p) => h('option', { value: p, selected: (v.pos || '') === p }, p || '—')));
  const el = h('div', { class: 'form-grid' },
    input('lemma', 'Word (dictionary form)', lang === 'sv' ? 'e.g. bil' : 'e.g. maison'),
    input('translation', 'Meaning'),
    h('label', { class: 'field' }, lang === 'sv' ? 'en / ett' : 'Gender', f.gender),
    h('label', { class: 'field' }, 'Part of speech', f.pos),
    h('div', { class: 'full' }, input('forms', 'Forms', lang === 'sv' ? 'en bil – bilen – bilar – bilarna' : 'un cheval – des chevaux')),
    h('div', { class: 'full' }, input('example', 'Example sentence')),
    h('div', { class: 'full' }, input('example_translation', 'Example translation')),
    h('div', { class: 'full' }, input('notes', 'Notes')));
  const values = () => Object.fromEntries(Object.entries(f).map(([k, e]) => [k, e.value.trim()]));
  const fill = (data) => { for (const [k, val] of Object.entries(data)) if (f[k] && val !== undefined) f[k].value = val; };
  return { el, values, fill };
}

export async function addWordDialog(lang, word = '', context = '', sessionId = null, onDone = null) {
  const form = wordForm(lang, { lemma: word });
  const status = h('div', { class: 'small faint' });
  const autofill = async () => {
    const w = form.values().lemma;
    if (!w) return;
    mount(status, spinner(), ' Looking it up…');
    try { form.fill(await api.post('/api/vocab/autofill', { language: lang, word: w, context })); mount(status, 'Filled in by your local model — check it.'); }
    catch (e) { mount(status, 'Autofill failed: ' + e.message); }
  };
  const ankiOk = state.status?.anki?.ok;
  const save = async (toAnki) => {
    const v = form.values();
    if (!v.lemma) throw new Error('Please enter a word');
    const row = await api.post('/api/vocab', { language: lang, ...v, session_id: sessionId, status: 'learning' });
    if (toAnki) {
      const r = await api.post('/api/vocab/bulk', { ids: [row.id], action: 'anki' });
      if (r.failed?.length) toast(`Saved, but Anki failed: ${r.failed[0].error}`, 'error', 6000);
      else toast(`"${row.lemma}" added to Anki`, 'success');
    } else toast(`"${row.lemma}" saved`, 'success');
    onDone && onDone();
  };
  modal({
    title: 'Add a word', wide: true,
    body: h('div', { class: 'col' }, form.el, h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: autofill }, icon('sparkle', 14), 'Autofill'), status)),
    actions: [
      { label: 'Cancel' },
      { label: 'Save', onClick: () => save(false) },
      { label: 'Save & send to Anki', class: 'primary', onClick: () => { if (!ankiOk) throw new Error('Anki is not open'); return save(true); } },
    ],
  });
  if (word) autofill();
}

function editWord(v, onDone) {
  const form = wordForm(v.language, v);
  modal({
    title: `Edit "${v.lemma}"`, wide: true, body: form.el,
    actions: [{ label: 'Cancel' }, { label: 'Save', class: 'primary', onClick: async () => { await api.patch(`/api/vocab/${v.id}`, form.values()); onDone(); } }],
  });
}
