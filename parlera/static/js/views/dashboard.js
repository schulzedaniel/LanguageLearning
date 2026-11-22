import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, progressBar, fmtDate, fmtDuration, empty } from '../ui.js';
import { navigate } from '../nav.js';
import { openStartDialog, startSession } from './start.js';

const MODE_LABEL = { lesson: 'Lesson', conversation: 'Conversation', roleplay: 'Role-play', review: 'Review', exam: 'Exam', writing: 'Writing', placement: 'Placement', free: 'Free talk', pronunciation: 'Pronunciation' };

export default async function dashboard(main) {
  mount(main, loading());
  const lang = state.language;
  const L = LANGS[lang];
  const [d, status] = await Promise.all([api.get(`/api/dashboard/${lang}`), api.get('/api/status').catch(() => null)]);
  const unit = d.unit;
  const prog = d.unit_progress || {};
  const name = state.settings.learner?.name;
  const firstTime = d.stats.sessions === 0;

  const setup = setupCallouts(status);

  const hero = h('div', { class: 'card hero' },
    h('div', { class: 'hero-main' },
      h('div', { class: 'row' }, h('span', { class: 'level-pill' }, unit.level), h('span', { class: 'faint small' }, `Unit ${unit.index + 1} of ${d.stats.levels.reduce((a, l) => a + l.total, 0)}`)),
      h('h2', {}, unit.title),
      h('div', { class: 'muted' }, unit.topic),
      h('div', { class: 'row mt', style: { maxWidth: '420px' } }, h('div', { class: 'grow' }, progressBar(prog.mastery || 0)),
        h('span', { class: 'small muted' }, `${Math.round((prog.mastery || 0) * 100)}% · ${prog.sessions || 0} session${prog.sessions === 1 ? '' : 's'}`)),
      h('div', { class: 'modes' },
        h('button', { class: 'btn primary lg', onclick: () => startSession({ mode: 'lesson' }) }, icon('play', 16), prog.sessions ? 'Continue lesson' : 'Start lesson'),
        h('button', { class: 'btn', onclick: () => startSession({ mode: 'conversation' }) }, icon('chat', 16), 'Conversation'),
        h('button', { class: 'btn', onclick: () => openStartDialog({ mode: 'roleplay' }) }, icon('theater', 16), 'Role-play'),
        h('button', { class: 'btn', onclick: () => startSession({ mode: 'review' }) }, icon('refresh', 16), 'Review'),
        h('button', { class: 'btn', onclick: () => startSession({ mode: 'pronunciation' }) }, icon('wave', 16), 'Pronunciation'),
        h('button', { class: 'btn ghost', onclick: () => openStartDialog() }, icon('more', 16), 'More…')),
      firstTime && lang === 'fr' ? h('div', { class: 'callout mt' }, icon('lightbulb'),
        h('div', {}, 'Had French at school? A ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); startSession({ mode: 'placement' }); } }, 'placement check'),
          ' finds out what you still know, so you can skip ahead.')) : null),
    h('div', { class: 'hero-side' },
      h('div', { class: 'section-label', style: { marginTop: 0 } }, 'By the end of this unit you can'),
      h('ul', { class: 'cando' }, (unit.can_do || []).map((g) => h('li', {}, g))),
      d.next_unit ? h('div', { class: 'small faint mt' }, 'Next: ', d.next_unit.title) : null,
      prog.mastery >= (state.settings.curriculum?.advance_threshold ?? 0.75) && d.next_unit
        ? h('button', { class: 'btn sm mt', onclick: async () => { await api.post(`/api/learner/${lang}/advance`); dashboard(main); } }, icon('arrowRight', 14), 'Move to next unit')
        : null));

  const s = d.stats;
  const stats = h('div', { class: 'grid c4' },
    stat('flame', 'Streak', `${s.streak} day${s.streak === 1 ? '' : 's'}`, s.streak ? 'Keep it going!' : 'Practise today to start one'),
    stat('clock', 'This week', `${s.week_minutes} min`, `${s.total_minutes} min in total`),
    stat('chat', 'Sessions', `${s.sessions}`, `${s.completed_sessions} reviewed`),
    stat('cards', 'Words', `${s.vocab.learning + s.vocab.known}`, `${s.vocab.known} known · ${s.vocab.learning} learning`));

  const curLevel = unit.level;
  const path = h('div', { class: 'card' },
    h('div', { class: 'card-head' }, h('h3', {}, 'Your path'), h('a', { href: '#/curriculum', class: 'small' }, 'Open curriculum →')),
    h('div', { class: 'path' }, s.levels.map((lv) => h('div', { class: `path-step ${lv.code === curLevel ? 'current' : ''}` },
      h('div', { class: 'row between' }, h('span', { class: 'code' }, lv.code), h('span', { class: 'tiny faint' }, `${lv.completed}/${lv.total}`)),
      h('div', { class: 'small muted', style: { margin: '2px 0 8px', minHeight: '20px' } }, lv.title.split('–').pop().trim()),
      progressBar(lv.total ? lv.completed / lv.total : 0, 'thin good'),
      lv.exam ? h('div', { class: 'tiny faint mt', title: 'Average of your last exam simulations' }, icon('award', 12), ' ', lv.exam_readiness != null ? `Exam readiness ${Math.round(lv.exam_readiness * 100)}%` : lv.exam.replace(' – production orale', '').replace(' (oral part)', '').split(' (')[0]) : null))),
    h('div', { class: 'small faint mt' }, 'Last 30 days'),
    heatmap(s.practice_days));

  const recent = h('div', { class: 'card' },
    h('div', { class: 'card-head' }, h('h3', {}, 'Recent sessions'), h('a', { href: '#/history', class: 'small' }, 'All sessions →')),
    d.recent_sessions.length ? h('div', { class: 'list' }, d.recent_sessions.map((r) => h('div', {
      class: 'list-item clickable', onclick: () => navigate(r.status === 'completed' ? `review/${r.id}` : `session/${r.id}`),
    },
      h('span', { class: 'badge' }, MODE_LABEL[r.mode] || r.mode),
      h('div', { class: 'grow' }, h('div', { style: { fontWeight: 600 } }, r.title), h('div', { class: 'tiny faint' }, `${fmtDate(r.created_at, { time: true })} · ${fmtDuration(r.duration)}`)),
      r.status === 'active' ? h('span', { class: 'badge warn' }, 'Resume') : h('span', { class: 'badge good' }, icon('check', 12), 'Reviewed'))))
      : empty('chat', `No sessions yet. Say ${L.hello} to ${L.tutor}!`));

  const focus = h('div', { class: 'card' },
    h('div', { class: 'card-head' }, h('h3', {}, 'Focus areas'), h('a', { href: '#/memory', class: 'small' }, 'Details →')),
    d.errors.length || d.weak_vocab.length ? h('div', { class: 'col' },
      d.errors.length ? h('div', {}, h('div', { class: 'section-label', style: { marginTop: 0 } }, 'Recurring mistakes'),
        d.errors.map((e) => h('div', { class: 'row small', style: { margin: '5px 0' } }, h('span', { class: 'badge warn' }, `${e.count}×`), h('span', {}, e.pattern)))) : null,
      d.weak_vocab.length ? h('div', {}, h('div', { class: 'section-label' }, 'Words to review'),
        h('div', { class: 'chips' }, d.weak_vocab.map((v) => h('span', { class: 'chip' }, v.display, h('span', { class: 'm' }, v.translation))))) : null,
      h('button', { class: 'btn sm', style: { alignSelf: 'flex-start' }, onclick: () => startSession({ mode: 'review' }) }, icon('refresh', 14), 'Practise these'))
      : empty('target', 'Your mistakes and tricky words will show up here after your first sessions.'));

  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, `${L.hello}${name ? ', ' + name : ''}! ${L.flag}`),
        h('div', { class: 'sub' }, firstTime ? `Welcome to ${L.name}. ${L.tutor} is ready for your first lesson.` : `${L.name} · level ${unit.level} · ${d.immersion}% immersion`)),
      h('button', { class: 'btn', onclick: () => openStartDialog() }, icon('plus', 16), 'New session')),
    setup,
    hero,
    h('div', { class: 'mt-lg' }, stats),
    h('div', { class: 'grid c2 mt-lg' }, path, h('div', { class: 'col gap-lg' }, recent, focus))));
}

function stat(ic, label, value, sub) {
  return h('div', { class: 'card stat' }, h('div', { class: 'l' }, icon(ic, 14), label), h('div', { class: 'v' }, value), h('div', { class: 's' }, sub));
}

function heatmap(days) {
  const set = new Set(days);
  const cells = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    cells.push(h('i', { class: set.has(iso) ? 'on' : '', title: iso }));
  }
  return h('div', { class: 'heat' }, cells);
}

function setupCallouts(status) {
  if (!status) return null;
  const items = [];
  if (!status.ollama.ok) {
    items.push(h('div', { class: 'callout bad mb' }, icon('alert'), h('div', {}, h('b', {}, 'Ollama is not running. '),
      'Start the Ollama app (or run ', h('code', {}, 'ollama serve'), '), then reload this page.')));
  } else if (!status.ollama.model_installed) {
    items.push(h('div', { class: 'callout warn mb' }, icon('alert'), h('div', {}, h('b', {}, `Model "${status.ollama.model}" isn't installed. `),
      'Run ', h('code', {}, `ollama pull ${status.ollama.model}`), ' in Terminal, or choose another model in ', h('a', { href: '#/settings' }, 'Settings'), '.')));
  }
  if (!status.stt.available) {
    items.push(h('div', { class: 'callout warn mb' }, icon('micOff'), h('div', {}, h('b', {}, 'Speech input is off. '),
      'You can type for now. On a Mac run ', h('code', {}, './setup.sh'), ' again or ', h('code', {}, 'pip install mlx-whisper'), ' to talk with your voice.')));
  }
  return items.length ? h('div', {}, items) : null;
}
