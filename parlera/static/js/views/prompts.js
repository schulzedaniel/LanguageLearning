// Editor for the teacher's system prompts (Jinja2 Markdown templates in the data folder).
import { api, state } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, modal, spinner } from '../ui.js';

const VARS = [
  ['language_name', 'Swedish / French'], ['native_language', 'your language'], ['learner_name', 'your name'],
  ['learner_goal', 'goal from Settings'], ['learner_notes', 'notes (Memory page)'], ['level', 'A1…B2'],
  ['immersion', '% target language'], ['unit.title', 'current unit'], ['unit.topic', ''], ['unit.can_do', 'list'],
  ['unit.grammar', 'list'], ['unit.vocabulary', 'list'], ['unit.phrases', 'list'], ['unit.scenarios', 'list'],
  ['unit_progress.sessions', ''], ['unit_progress.mastery', '0–1'], ['memories', 'list of facts'],
  ['recent_summaries', 'list (title, summary)'], ['weak_vocab', 'list'], ['recurring_errors', 'list (pattern, count)'],
  ['mode', 'lesson, exam…'], ['scenario', 'role-play'], ['focus', 'session focus'], ['exam.name', ''], ['exam.format', ''],
  ['transcript', 'analysis only'],
];

export default async function prompts(main) {
  mount(main, loading());
  let list = await api.get('/api/prompts');
  let currentName = list[0]?.name;
  let current = null;
  let dirty = false;

  const listEl = h('div', { class: 'col', style: { gap: '2px' } });
  const editorEl = h('div');

  function renderList() {
    const groups = {};
    for (const p of list) (groups[p.group] ||= []).push(p);
    mount(listEl, ...Object.entries(groups).map(([g, items]) => h('div', {},
      h('div', { class: 'section-label' }, g),
      items.map((p) => h('div', { class: `list-item clickable ${p.name === currentName ? 'active' : ''}`, style: { padding: '8px 10px', borderBottom: 0 }, onclick: () => select(p.name) },
        h('div', { class: 'grow small', style: { fontWeight: 600 } }, p.title), p.modified ? h('span', { class: 'badge accent', title: 'Edited by you' }, 'edited') : null)))));
  }

  async function select(name) {
    if (dirty && !(await confirmDialog('You have unsaved changes. Discard them?', { ok: 'Discard', danger: true }))) return;
    currentName = name; dirty = false;
    renderList();
    mount(editorEl, loading());
    current = await api.get(`/api/prompts/${name}`);
    renderEditor();
  }

  function renderEditor() {
    const ta = h('textarea', { class: 'code', spellcheck: 'false' }, current.text);
    ta.addEventListener('input', () => { dirty = true; saveBtn.disabled = false; });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Tab') { e.preventDefault(); ta.setRangeText('  ', ta.selectionStart, ta.selectionEnd, 'end'); }
      if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); save(); }
    });
    const save = async () => {
      try {
        await api.put(`/api/prompts/${current.name}`, { text: ta.value });
        dirty = false; saveBtn.disabled = true;
        list = await api.get('/api/prompts'); renderList();
        toast('Saved — applies from the next message', 'success');
      } catch (e) { toast(e.message, 'error', 7000); }
    };
    const saveBtn = h('button', { class: 'btn primary', disabled: true, onclick: save }, 'Save');
    mount(editorEl, h('div', { class: 'card' },
      h('div', { class: 'card-head' },
        h('div', {}, h('h3', {}, current.title), h('div', { class: 'small muted' }, current.description), h('div', { class: 'tiny faint mono' }, `prompts/${current.name}.md`)),
        h('div', { class: 'row' },
          current.has_default ? h('button', { class: 'btn ghost', disabled: !current.modified, onclick: async () => {
            if (!(await confirmDialog('Replace this prompt with the built-in default?', { ok: 'Reset', danger: true }))) return;
            current = await api.post(`/api/prompts/${current.name}/reset`); dirty = false;
            list = await api.get('/api/prompts'); renderList(); renderEditor(); toast('Reset to default');
          } }, 'Reset') : null,
          h('button', { class: 'btn', onclick: () => preview() }, icon('eye', 15), 'Preview'),
          saveBtn)),
      ta,
      h('details', { class: 'mt' }, h('summary', { class: 'small', style: { cursor: 'pointer', fontWeight: 600 } }, 'Template variables & syntax'),
        h('div', { class: 'small muted mt' }, 'Use ', h('code', {}, '{{ variable }}'), ' to insert values, ', h('code', {}, '{% if x %}…{% endif %}'), ' and ', h('code', {}, '{% for m in memories %}…{% endfor %}'),
          ' for logic, ', h('code', {}, '{# comment #}'), ' for notes. Tip: tell the tutor to put target-language text in ', h('code', {}, '**bold**'), ' — the voice engine relies on it.'),
        h('div', { class: 'vars mt' }, VARS.map(([v, d]) => h('div', {}, h('code', {}, v), d ? ` — ${d}` : ''))))));
  }

  async function preview() {
    const mode = h('select', {}, ['lesson', 'conversation', 'roleplay', 'review', 'exam', 'writing', 'placement', 'free'].map((m) => h('option', { value: m }, m)));
    const out = h('div', { class: 'mt' }, spinner());
    const run = async () => {
      mount(out, spinner());
      try {
        const r = await api.post('/api/prompts-preview', { language: state.language, mode: mode.value });
        mount(out, h('div', { class: 'small faint mb' }, `${r.chars} characters ≈ ${r.approx_tokens} tokens · saved changes only`),
          h('pre', { class: 'prompt-preview' }, r.system), h('div', { class: 'section-label' }, 'First (hidden) message'), h('pre', { class: 'prompt-preview' }, r.opening));
      } catch (e) { mount(out, h('div', { class: 'callout bad' }, e.message)); }
    };
    mode.addEventListener('change', run);
    modal({ title: 'Full system prompt preview', wide: true, body: h('div', {}, h('label', { class: 'field' }, 'Session type', mode), out) });
    run();
  }

  mount(main, h('div', { class: 'page', style: { maxWidth: '1280px' } },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Teacher prompts'),
      h('div', { class: 'sub' }, 'Shape how your tutor behaves. These Markdown templates are combined into the system prompt for each session (base rules → persona → your context → session type).'))),
    h('div', { class: 'editor-layout' }, h('div', {}, listEl), editorEl)));
  renderList();
  if (currentName) select(currentName);
  return () => {};
}
