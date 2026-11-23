// Curriculum browser, unit details and YAML editor.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, progressBar } from '../ui.js';
import { startSession, openStartDialog } from './start.js';
import { unitChecklist, statusFromProgress } from './progress.js';

export default async function curriculum(main) {
  const lang = state.language;
  mount(main, loading());
  let data = await api.get(`/api/curriculum/${lang}`);
  let drawer = null;

  function render() {
    const cur = data.curriculum;
    const levels = cur.levels.map((lv) => {
      const done = lv.units.filter((u) => data.progress[u.id]?.status === 'completed').length;
      return h('section', {},
        h('div', { class: 'level-head' }, h('span', { class: 'level-pill' }, lv.code), h('h2', {}, lv.title),
          h('span', { class: 'small muted' }, `${done} of ${lv.units.length} units done`),
          h('div', { style: { width: '120px' } }, progressBar(lv.units.length ? done / lv.units.length : 0, 'thin good')),
          lv.exam?.name ? h('span', { class: 'badge', title: lv.exam.format || '' }, icon('award', 12), lv.exam.name) : null),
        lv.description ? h('p', { class: 'muted small', style: { marginTop: '-6px' } }, lv.description) : null,
        h('div', { class: 'units' }, lv.units.map((u) => unitCard(u))));
    });
    mount(main, h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('h1', {}, `${LANGS[lang].name} curriculum`), h('div', { class: 'sub' }, cur.description || '')),
        h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => openEditor() }, icon('edit', 16), 'Edit YAML'))),
      cur.exams?.length ? h('div', { class: 'card flat mb' }, h('div', { class: 'row wrap' }, icon('award'), h('b', {}, 'Exam milestones:'),
        cur.exams.map((e) => h('span', { class: 'badge accent', title: e.description || '' }, `${e.name} · ${(e.levels || []).join('/')}`)))) : null,
      levels));
  }

  function unitCard(u) {
    const p = data.progress[u.id];
    const isCurrent = u.id === data.current_unit_id;
    const completed = p?.status === 'completed';
    return h('div', { class: `unit-card ${isCurrent ? 'current' : ''} ${completed ? 'completed' : ''}`, onclick: () => openUnit(u) },
      h('div', { class: 'row between' }, h('span', { class: 'num' }, `UNIT ${u.index + 1}`),
        completed ? h('span', { class: 'badge good' }, icon('check', 12), 'done') : isCurrent ? h('span', { class: 'badge accent' }, 'current') : null),
      h('div', { class: 't' }, u.title),
      h('div', { class: 'small faint', style: { flex: 1 } }, u.topic),
      p && (p.sessions || p.status === 'completed') ? unitChecklist(statusFromProgress(u, p, data.threshold ?? 0.75), { compact: true })
        : isCurrent ? h('div', { class: 'tiny faint' }, 'Not started yet') : null);
  }

  function openUnit(u) {
    drawer?.remove();
    const p = data.progress[u.id] || {};
    const isCurrent = u.id === data.current_unit_id;
    const list = (title, items, fn = (x) => x) => items?.length ? [h('div', { class: 'section-label' }, title), h('div', { class: 'col', style: { gap: '4px' } }, items.map((x) => h('div', { class: 'small' }, fn(x))))] : [];
    const pairs = (title, items) => items?.length ? [h('div', { class: 'section-label' }, title),
      h('div', {}, items.map((p2) => h('div', { class: 'phrase', style: { cursor: 'default' } }, h('span', { class: 't' }, p2.term), h('span', { class: 'm' }, p2.meaning))))] : [];
    const act = async (action, extra = {}) => {
      await api.post(`/api/curriculum/${lang}/units/${u.id}`, { action, ...extra });
      data = await api.get(`/api/curriculum/${lang}`);
      render(); openUnit(u);
    };
    drawer = h('div', { class: 'drawer' },
      h('div', { class: 'drawer-head' },
        h('div', {}, h('div', { class: 'row' }, h('span', { class: 'level-pill' }, u.level), h('span', { class: 'small faint' }, `Unit ${u.index + 1} · ${u.id}`)),
          h('h2', { class: 'mt' }, u.title), h('div', { class: 'muted small' }, u.topic)),
        h('button', { class: 'btn ghost icon', onclick: () => { drawer.remove(); drawer = null; } }, icon('x'))),
      h('div', { class: 'drawer-body' },
        h('div', { class: 'section-label', style: { marginTop: '4px' } }, 'To complete this unit'),
        unitChecklist(statusFromProgress(u, p, data.threshold ?? 0.75)),
        ...list('Can-do goals', u.can_do, (g) => h('span', { class: 'goal' }, icon('target', 14), g)),
        ...list('Grammar', u.grammar, (g) => h('span', { class: 'row between', style: { width: '100%' } }, h('span', {}, g),
          h('button', { class: 'btn ghost sm', title: 'A short lecture on this grammar point (Practice → Grammar explained)', onclick: async () => { const { explainGrammar } = await import('./practice.js'); explainGrammar(lang, g, u.id); } }, icon('lightbulb', 13), 'Explain'))),
        ...pairs('Vocabulary', u.vocab_pairs),
        ...pairs('Phrases', u.phrase_pairs),
        u.pronunciation ? [h('div', { class: 'section-label' }, 'Pronunciation'), h('div', { class: 'small' }, u.pronunciation)] : null,
        u.culture ? [h('div', { class: 'section-label' }, 'Culture'), h('div', { class: 'small' }, u.culture)] : null,
        ...list('Role-play ideas', u.scenarios)),
      h('div', { class: 'drawer-foot' },
        h('button', { class: 'btn primary', onclick: () => { if (!isCurrent) api.post(`/api/curriculum/${lang}/units/${u.id}`, { action: 'set_current' }).then(() => startSession({ mode: 'lesson', unit_id: u.id })); else startSession({ mode: 'lesson', unit_id: u.id }); } }, icon('play', 15), 'Start lesson'),
        h('button', { class: 'btn', onclick: () => openStartDialog({ unit_id: u.id }) }, 'Other session…'),
        !isCurrent ? h('button', { class: 'btn', onclick: () => act('set_current') }, 'Make current') : null,
        p.status === 'completed'
          ? h('button', { class: 'btn ghost', onclick: () => act('active') }, 'Mark not done')
          : h('button', { class: 'btn ghost', onclick: () => act('completed') }, icon('check', 15), 'Mark done')));
    document.body.append(drawer);
  }

  async function openEditor() {
    drawer?.remove();
    const raw = await api.get(`/api/curriculum/${lang}/raw`);
    const ta = h('textarea', { class: 'code', spellcheck: 'false', style: { minHeight: '68vh' } }, raw);
    const msg = h('div', { class: 'small' });
    const validate = async () => {
      const r = await api.post(`/api/curriculum/${lang}/validate`, { text: ta.value });
      mount(msg, r.ok ? h('span', { style: { color: 'var(--good)' } }, `✓ Valid — ${r.units} units in ${r.levels.join(', ')}`) : h('span', { style: { color: 'var(--bad)' } }, r.error));
      return r.ok;
    };
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Tab') { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText('  ', s, ta.selectionEnd, 'end'); }
      if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save(); }
    });
    const save = async () => {
      if (!(await validate())) return;
      try { await api.put(`/api/curriculum/${lang}/raw`, { text: ta.value }); toast('Curriculum saved', 'success'); data = await api.get(`/api/curriculum/${lang}`); }
      catch (e) { toast(e.message, 'error'); }
    };
    mount(main, h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('h1', {}, 'Edit curriculum'), h('div', { class: 'sub' }, 'YAML file in your data folder. Keep unit ids stable — progress is stored per id. ', h('kbd', {}, '⌘S'), ' saves.')),
        h('div', { class: 'row' },
          h('button', { class: 'btn ghost', onclick: () => render() }, icon('arrowLeft', 16), 'Back'),
          h('button', { class: 'btn danger', onclick: async () => { if (await confirmDialog('Replace your curriculum with the built-in default? Your edits will be lost (progress is kept).', { danger: true, ok: 'Reset' })) { await api.post(`/api/curriculum/${lang}/reset`); toast('Reset to default', 'success'); openEditor(); } } }, 'Reset to default'),
          h('button', { class: 'btn', onclick: validate }, 'Validate'),
          h('button', { class: 'btn primary', onclick: save }, 'Save'))),
      msg, h('div', { class: 'mt' }, ta)));
  }

  render();
  return () => drawer?.remove();
}
