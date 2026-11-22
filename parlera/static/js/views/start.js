// "Start a session" dialog: pick mode, unit, scenario and an optional focus.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, modal, toast } from '../ui.js';
import { navigate } from '../nav.js';

const MODE_ORDER = ['lesson', 'conversation', 'roleplay', 'review', 'pronunciation', 'exam', 'writing', 'placement', 'free'];

export async function startSession({ mode = 'lesson', unit_id = null, scenario = '', focus = '' } = {}) {
  const lang = state.language;
  const s = await api.post('/api/sessions', { language: lang, mode, unit_id, scenario, focus });
  navigate(`session/${s.id}`);
}

export async function openStartDialog(opts = {}) {
  const lang = state.language;
  const [cur, status] = await Promise.all([api.get(`/api/curriculum/${lang}`), api.get('/api/status').catch(() => null)]);
  const modes = status?.modes || {};
  const units = cur.curriculum.units;
  let mode = opts.mode || 'lesson';
  let unitId = opts.unit_id || cur.current_unit_id;

  const unitSelect = h('select', {},
    cur.curriculum.levels.map((lv) => h('optgroup', { label: `${lv.code} · ${lv.title || ''}` },
      lv.units.map((u) => h('option', { value: u.id, selected: u.id === unitId },
        `${u.index + 1}. ${u.title}${u.id === cur.current_unit_id ? '  (current)' : ''}${cur.progress[u.id]?.status === 'completed' ? '  ✓' : ''}`)))));
  unitSelect.addEventListener('change', () => { unitId = unitSelect.value; renderScenarios(); });

  const scenarioSelect = h('select', {});
  const scenarioCustom = h('input', { type: 'text', placeholder: 'Or describe your own scenario, e.g. "Returning a broken phone to a shop"' });
  const focusInput = h('textarea', { rows: 2, placeholder: 'Optional: anything you want to focus on today (e.g. "I keep mixing up en/ett", "prepare for a job interview")' }, opts.focus || '');

  function renderScenarios() {
    const u = units.find((x) => x.id === unitId);
    mount(scenarioSelect, h('option', { value: '' }, 'Let the tutor choose'),
      ...(u?.scenarios || []).map((s) => h('option', { value: s }, s)));
  }
  renderScenarios();

  const unitRow = h('label', { class: 'field' }, 'Unit', unitSelect);
  const scenarioRow = h('div', { class: 'col' }, h('label', { class: 'field' }, 'Scenario', scenarioSelect), scenarioCustom);
  const grid = h('div', { class: 'grid c2' });

  function renderModes() {
    mount(grid, ...MODE_ORDER.filter((m) => modes[m]).map((m) => h('button', {
      class: `mode-card ${m === mode ? 'active' : ''}`,
      onclick: () => { mode = m; renderModes(); },
    }, h('span', { class: 'ic' }, icon(modes[m].icon, 18)), h('div', {}, h('b', {}, modes[m].title), h('span', {}, modes[m].description)))));
    unitRow.classList.toggle('hidden', !modes[mode]?.unit);
    scenarioRow.classList.toggle('hidden', mode !== 'roleplay');
  }
  renderModes();

  const body = h('div', { class: 'col gap-lg' },
    grid, unitRow, scenarioRow, h('label', { class: 'field' }, 'Focus (optional)', focusInput));

  const m = modal({
    title: `New ${LANGS[lang].name} session`, wide: true, body,
    actions: [
      { label: 'Cancel' },
      { label: 'Start session', class: 'primary', onClick: async () => {
        try {
          await startSession({
            mode, unit_id: modes[mode]?.unit ? unitId : null,
            scenario: mode === 'roleplay' ? (scenarioCustom.value.trim() || scenarioSelect.value) : '',
            focus: focusInput.value.trim(),
          });
        } catch (e) { toast(e.message, 'error'); return false; }
        return true;
      } },
    ],
  });
  return m.done;
}
