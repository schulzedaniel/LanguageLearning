// What the tutor remembers about you + your recurring mistakes.
import { renderMarkdown } from '../markdown.js';
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, modal, fmtDate, empty } from '../ui.js';
import { startWorkshop } from './start.js';

const CATS = { personal: 'Personal', preference: 'Lesson preference', goal: 'Goal', other: 'Other' };

export default async function memory(main) {
  const lang = state.language;
  const L = LANGS[lang];
  let tab = 'memories';
  mount(main, loading());

  const body = h('div');
  const tabs = h('div', { class: 'tabs' });

  async function render() {
    const [mems, errs, learner, directives] = await Promise.all([api.get(`/api/memories?language=${lang}`), api.get(`/api/errors?language=${lang}`), api.put(`/api/learner/${lang}`, {}), api.get(`/api/directives?language=${lang}`)]);
    mount(tabs, 
      h('button', { class: tab === 'memories' ? 'active' : '', onclick: () => { tab = 'memories'; render(); } }, icon('brain', 15), 'Memories', h('span', { class: 'count' }, mems.length)),
      h('button', { class: tab === 'errors' ? 'active' : '', onclick: () => { tab = 'errors'; render(); } }, icon('target', 15), 'Recurring mistakes', h('span', { class: 'count' }, errs.filter((e) => !e.resolved).length)),
      h('button', { class: tab === 'directives' ? 'active' : '', onclick: () => { tab = 'directives'; render(); } }, icon('mail', 15), 'Teacher instructions', h('span', { class: 'count' }, directives.filter((d) => d.active && !d.expired).length)),
      h('button', { class: tab === 'notes' ? 'active' : '', onclick: () => { tab = 'notes'; render(); } }, icon('pen', 15), 'Notes for the tutor'));
    if (tab === 'memories') mount(body, memList(mems));
    else if (tab === 'errors') mount(body, errList(errs));
    else if (tab === 'directives') mount(body, dirList(directives));
    else mount(body, notes(learner));
  }

  function memList(mems) {
    return h('div', { class: 'col' },
      h('div', { class: 'row between' }, h('div', { class: 'small muted' }, `Facts ${L.tutor} uses to personalise lessons. They're extracted after each session — edit or switch off anything you like.`),
        h('button', { class: 'btn primary sm', onclick: () => editMem(null) }, icon('plus', 14), 'Add')),
      mems.length ? h('div', { class: 'card', style: { padding: '6px 14px' } }, h('div', { class: 'list' }, mems.map((m) => h('div', { class: 'list-item', style: { opacity: m.active ? 1 : 0.5 } },
        h('button', { class: `btn ghost icon sm`, title: m.pinned ? 'Unpin' : 'Pin (always included)', style: { color: m.pinned ? 'var(--accent)' : '' }, onclick: async () => { await api.patch(`/api/memories/${m.id}`, { pinned: m.pinned ? 0 : 1 }); render(); } }, icon('pin', 15)),
        h('div', { class: 'grow' }, h('div', {}, m.content),
          h('div', { class: 'tiny faint' }, `${CATS[m.category] || m.category} · ${m.language ? LANGS[m.language]?.name : 'all languages'} · ${fmtDate(m.created_at)}`)),
        h('label', { class: 'check small', title: 'Use in sessions' }, h('input', { type: 'checkbox', checked: !!m.active, onchange: async (e) => { await api.patch(`/api/memories/${m.id}`, { active: e.target.checked ? 1 : 0 }); render(); } }), 'active'),
        h('button', { class: 'btn ghost icon sm', onclick: () => editMem(m) }, icon('edit', 15)),
        h('button', { class: 'btn ghost icon sm', onclick: async () => { if (await confirmDialog('Forget this?', { danger: true, ok: 'Forget' })) { await api.del(`/api/memories/${m.id}`); render(); } } }, icon('trash', 15))))))
        : empty('brain', `${L.tutor} doesn't know anything about you yet. Tell them about yourself in a session, or add facts here.`));
  }

  function editMem(m) {
    const content = h('textarea', { rows: 3, placeholder: 'e.g. "Works as a nurse and wants to move to Gothenburg next year."' }, m?.content || '');
    const cat = h('select', {}, Object.entries(CATS).map(([k, v]) => h('option', { value: k, selected: (m?.category || 'personal') === k }, v)));
    const scope = h('select', {}, h('option', { value: '' }, 'All languages'), Object.entries(LANGS).map(([k, v]) => h('option', { value: k, selected: m?.language === k }, `${v.name} only`)));
    modal({
      title: m ? 'Edit memory' : 'Add memory',
      body: h('div', { class: 'col' }, h('label', { class: 'field' }, 'What should the tutor remember?', content),
        h('div', { class: 'form-grid' }, h('label', { class: 'field' }, 'Category', cat), h('label', { class: 'field' }, 'Applies to', scope))),
      actions: [{ label: 'Cancel' }, { label: 'Save', class: 'primary', onClick: async () => {
        const body = { content: content.value.trim(), category: cat.value, language: scope.value || null };
        if (!body.content) throw new Error('Please write something');
        if (m) await api.patch(`/api/memories/${m.id}`, body); else await api.post('/api/memories', body);
        render();
      } }],
    });
  }

  function errList(errs) {
    return h('div', { class: 'col' },
      h('div', { class: 'row between' }, h('div', { class: 'small muted' }, 'Collected automatically from every session review. Unresolved ones are watched for in every lesson; the mistake workshop groups them, explains the rules and trains them. Patterns you master in a workshop are marked automatically.'),
        h('button', { class: 'btn primary sm', onclick: () => startWorkshop() }, icon('target', 14), 'Start mistake workshop')),
      errs.length ? h('div', { class: 'card', style: { padding: '6px 14px' } }, errs.map((e) => h('div', { class: 'err', style: { opacity: e.resolved ? 0.5 : 1 } },
        h('div', { class: 'row wrap' }, h('span', { class: 'badge warn' }, `${e.count}×`), h('span', { class: 'badge' }, e.category), h('b', { class: 'grow' }, e.pattern),
          h('span', { class: 'tiny faint' }, `last ${fmtDate(e.last_seen)}`),
          h('label', { class: 'check small' }, h('input', { type: 'checkbox', checked: !!e.resolved, onchange: async (ev) => { await api.patch(`/api/errors/${e.id}`, { resolved: ev.target.checked ? 1 : 0 }); render(); } }), 'mastered'),
          h('button', { class: 'btn ghost icon sm', onclick: async () => { await api.del(`/api/errors/${e.id}`); render(); } }, icon('trash', 14))),
        e.example_wrong ? h('div', {}, h('span', { class: 'wrong' }, e.example_wrong), '  →  ', h('span', { class: 'right' }, e.example_right)) : null,
        e.explanation ? h('div', { class: 'small muted', html: renderMarkdown(e.explanation).replace(/<\/?p>/g, '') }) : null)))
        : empty('target', 'No recurring mistakes recorded yet.'));
  }

  function dirList(rows) {
    return h('div', { class: 'col' },
      h('div', { class: 'row between' }, h('div', { class: 'small muted' }, `Instructions from your messages to ${L.tutor}. Active ones are added to every session until they expire.`),
        h('button', { class: 'btn primary sm', onclick: async () => { const { openTeacherNote } = await import('./teachernote.js'); await openTeacherNote(); render(); } }, icon('mail', 14), 'Message your teacher')),
      rows.length ? h('div', { class: 'card', style: { padding: '6px 14px' } }, h('div', { class: 'list' }, rows.map((d) => h('div', { class: 'list-item', style: { opacity: d.active && !d.expired ? 1 : 0.5 } },
        h('span', { class: 'badge' }, d.kind),
        h('div', { class: 'grow' }, h('div', {}, d.content),
          h('div', { class: 'tiny faint' }, `${d.language ? LANGS[d.language]?.name : 'all languages'} · ${d.expires_at ? (d.expired ? 'expired ' : 'until ') + fmtDate(d.expires_at) : 'permanent'}${d.source_text ? ` · from: “${d.source_text.slice(0, 80)}${d.source_text.length > 80 ? '…' : ''}”` : ''}`)),
        h('label', { class: 'check small' }, h('input', { type: 'checkbox', checked: !!d.active, onchange: async (e) => { await api.patch(`/api/directives/${d.id}`, { active: e.target.checked ? 1 : 0 }); render(); } }), 'active'),
        h('button', { class: 'btn ghost icon sm', onclick: async () => { await api.del(`/api/directives/${d.id}`); render(); } }, icon('trash', 15))))))
        : empty('mail', `No instructions yet. Use "Message your teacher" to tell ${L.tutor} what to focus on or change.`));
  }

  function notes(learner) {
    const ta = h('textarea', { rows: 8, placeholder: `Anything ${L.tutor} should always keep in mind, e.g. "I'm moving to Stockholm in June — prioritise everyday situations" or "Please correct my pronunciation more strictly."` }, learner.notes || '');
    return h('div', { class: 'card' }, h('h3', {}, `Notes for ${L.tutor}`),
      h('p', { class: 'small muted' }, 'Included in every session for this language.'), ta,
      h('div', { class: 'row mt' }, h('button', { class: 'btn primary', onclick: async () => { await api.put(`/api/learner/${lang}`, { notes: ta.value }); toast('Saved', 'success'); } }, 'Save')));
  }

  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Memory'), h('div', { class: 'sub' }, `What ${L.tutor} knows about you, and what you're working on.`))),
    tabs, body));
  await render();
}
