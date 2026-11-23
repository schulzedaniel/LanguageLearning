// "Start a session" dialog: pick mode, unit, scenario and an optional focus.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, modal, toast, fmtDate } from '../ui.js';
import { navigate } from '../nav.js';

const MODE_ORDER = ['lesson', 'conversation', 'roleplay', 'review', 'pronunciation', 'exam', 'writing', 'break', 'placement', 'free'];

export async function startSession({ mode = 'lesson', unit_id = null, scenario = '', focus = '', fresh = false } = {}) {
  const lang = state.language;
  // An unfinished session of the same kind exists? Offer to continue it instead of starting a duplicate.
  if (!fresh && !scenario && !focus) {
    const { session: open } = await api.get(`/api/sessions/open?language=${lang}&mode=${mode}${unit_id ? `&unit_id=${encodeURIComponent(unit_id)}` : ''}`).catch(() => ({}));
    if (open) {
      const choice = await modal({
        title: 'Continue where you left off?',
        body: h('div', { class: 'col' },
          h('p', {}, 'You have an unfinished session: ', h('b', {}, open.title), '.'),
          h('div', { class: 'small muted' }, `Last activity ${fmtDate(open.updated_at, { time: true })} · ${open.turns} turn${open.turns === 1 ? '' : 's'} so far. Your teacher remembers the whole conversation.`),
          h('div', { class: 'tiny faint' }, 'If you start fresh, the unfinished one moves to Sessions → Archive, so there is only ever one session to continue. You can still open it there.')),
        actions: [{ label: 'Start fresh', value: 'new' }, { label: 'Continue', class: 'primary', value: 'continue' }],
      }).done;
      if (!choice) return;
      if (choice === 'continue') { navigate(`session/${open.id}`); return; }
      await api.patch(`/api/sessions/${open.id}`, { archived: true }).catch(() => {});
    }
  }
  const s = await api.post('/api/sessions', { language: lang, mode, unit_id, scenario, focus });
  navigate(`session/${s.id}`);
}

export async function startWorkshop() {
  const lang = state.language;
  const overlay = h('div', { class: 'overlay' }, h('div', { class: 'overlay-box' }, h('span', { class: 'spinner lg' }),
    h('h2', {}, 'Preparing your mistake workshop…'),
    h('div', { class: 'muted' }, 'Your teacher is grouping your recent mistakes and working out the rules behind them. With "thinking" enabled this can take a few minutes.')));
  document.body.append(overlay);
  try {
    const s = await api.post('/api/workshops', { language: lang });
    overlay.remove();
    navigate(`session/${s.id}`);
  } catch (e) { overlay.remove(); toast(e.message, 'error', 8000); }
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
