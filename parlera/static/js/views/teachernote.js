// "Message your teacher": a note outside sessions → confirmed instructions for the system prompt.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, modal, toast, spinner } from '../ui.js';
import { navigate } from '../nav.js';

const DURATIONS = [[7, 'for 7 days'], [14, 'for 2 weeks'], [30, 'for 30 days'], [0, 'permanently']];

export function openTeacherNote() {
  const lang = state.language;
  const L = LANGS[lang];
  const ta = h('textarea', { rows: 5, placeholder: `Write to ${L.tutor} like a message, e.g.\n• "I have a job interview next Friday — let's practise for that this week."\n• "Please speak a bit slower and correct my pronunciation more."\n• "New words I learned today: ubiquitous, mitigate, nuance."` });
  const out = h('div', { class: 'col mt' });
  const current = h('div');
  let items = null;
  const manage = () => { m.close(); navigate('memory/directives'); };
  api.get(`/api/directives?language=${lang}`).then((rows) => {
    const act = rows.filter((d) => d.active && !d.expired);
    if (!act.length) return;
    mount(current, h('details', { class: 'current-dirs' },
      h('summary', {}, `${L.tutor} already follows ${act.length} instruction${act.length === 1 ? '' : 's'} from you`, h('a', { href: '#/memory/directives', class: 'small', style: { marginLeft: '10px' }, onclick: (e) => { e.preventDefault(); manage(); } }, 'View & edit →')),
      h('ul', { class: 'small' }, act.map((d) => h('li', {}, d.content, h('span', { class: 'faint' }, ` · ${d.language ? LANGS[d.language].name : 'all languages'}, ${d.expires_at ? 'until ' + d.expires_at.slice(0, 10) : 'permanent'}`))))));
  }).catch(() => {});
  const m = modal({
    title: `Message ${L.tutor}`, wide: true,
    body: h('div', {}, h('p', { class: 'small muted' }, `Your note is turned into instructions that ${L.tutor} follows in every session — temporarily or permanently. You confirm each one first. Later you find and edit them under Memory → Teacher instructions.`), current, ta, out),
    actions: [
      { label: 'Cancel' },
      { label: 'Suggest instructions', onClick: async () => { await suggest(); return false; } },
      { label: 'Save', class: 'primary', onClick: async () => {
        if (!items) { await suggest(); return false; }
        const chosen = items.filter((it) => it.keep);
        if (!chosen.length) throw new Error('Nothing selected');
        await api.post('/api/directives', { language: lang, text: ta.value, items: chosen });
        toast(h('span', {}, `${chosen.length} instruction(s) saved. ${L.tutor} follows them from the next reply on. `,
          h('a', { href: '#/memory/directives', style: { color: 'inherit', textDecoration: 'underline' } }, 'View & edit')), 'success', 7000);
      } },
    ],
  });
  async function suggest() {
    if (!ta.value.trim()) { toast('Write a note first', 'error'); return; }
    mount(out, h('div', { class: 'row small muted' }, spinner(), ' Reading your note…'));
    try {
      const r = await api.post('/api/teacher-note/parse', { language: lang, text: ta.value });
      items = r.items.map((it) => ({ ...it, keep: true, days: it.days || 0 }));
      render();
    } catch (e) { mount(out, h('div', { class: 'callout bad' }, e.message)); }
  }
  function render() {
    mount(out, h('div', { class: 'section-label' }, 'Instructions to add'),
      items.map((it) => h('div', { class: 'card flat', style: { padding: '10px 12px' } },
        h('div', { class: 'row', style: { alignItems: 'flex-start' } },
          h('input', { type: 'checkbox', checked: it.keep, style: { marginTop: '10px' }, onchange: (e) => { it.keep = e.target.checked; } }),
          h('div', { class: 'grow col', style: { gap: '6px' } },
            h('input', { type: 'text', value: it.content, oninput: (e) => { it.content = e.target.value; } }),
            h('div', { class: 'row wrap small' },
              h('span', { class: 'badge' }, it.kind),
              h('select', { style: { width: 'auto', padding: '4px 8px' }, onchange: (e) => { it.days = Number(e.target.value); } },
                DURATIONS.map(([d, l]) => h('option', { value: d, selected: Number(it.days) === d }, l)),
                DURATIONS.some(([d]) => d === Number(it.days)) ? null : h('option', { value: it.days, selected: true }, `for ${it.days} days`)),
              h('label', { class: 'check small' }, h('input', { type: 'checkbox', checked: it.all_languages, onchange: (e) => { it.all_languages = e.target.checked; } }), 'all my languages')))))));
  }
  setTimeout(() => ta.focus(), 50);
  return m.done;
}
