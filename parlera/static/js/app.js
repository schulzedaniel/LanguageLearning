// App shell: sidebar, language switch, status, hash router.
import { api, state, loadSettings, saveSettings, loadStatus, LANGS } from './api.js';
import { h, icon, mount, toast } from './ui.js';

import dashboard from './views/dashboard.js';
import session from './views/session.js';
import review from './views/review.js';
import curriculum from './views/curriculum.js';
import vocab from './views/vocab.js';
import history from './views/history.js';
import memory from './views/memory.js';
import prompts from './views/prompts.js';
import settings from './views/settings.js';
import practice from './views/practice.js';
import lecture from './views/lecture.js';

const ROUTES = [
  { path: '', view: dashboard, nav: 'Home', icon: 'home' },
  { path: 'practice', view: practice, nav: 'Practice', icon: 'puzzle' },
  { path: 'curriculum', view: curriculum, nav: 'Curriculum', icon: 'book' },
  { path: 'vocab', view: vocab, nav: 'Vocabulary', icon: 'cards' },
  { path: 'history', view: history, nav: 'Sessions', icon: 'clock' },
  { path: 'memory', view: memory, nav: 'Memory', icon: 'brain' },
  { sep: true },
  { path: 'prompts', view: prompts, nav: 'Teacher prompts', icon: 'pen' },
  { path: 'settings', view: settings, nav: 'Settings', icon: 'gear' },
  { path: 'practice/:tab', view: practice },
  { path: 'lecture/:id', view: lecture },
  { path: 'session/:id', view: session },
  { path: 'review/:id', view: review },
];

let cleanup = null;
let pushedPending = false;

function match(hash) {
  const path = hash.replace(/^#\/?/, '');
  for (const r of ROUTES) {
    if (r.sep) continue;
    const keys = [];
    const re = new RegExp('^' + r.path.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '$');
    const m = path.match(re);
    if (m) return { route: r, params: Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
  }
  return { route: ROUTES[0], params: {} };
}

import { navigate, applyTheme } from './nav.js';

async function render() {
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const { route, params } = match(location.hash);
  renderNav(route);
  const main = document.getElementById('main');
  main.scrollTop = 0;
  try {
    cleanup = (await route.view(main, params)) || null;
  } catch (e) {
    console.error(e);
    mount(main, h('div', { class: 'page' }, h('div', { class: 'callout bad' }, icon('alert'), h('div', {}, h('b', {}, 'Something went wrong. '), e.message))));
  }
}

function renderNav(active) {
  const nav = document.getElementById('nav');
  mount(nav, ROUTES.filter((r) => r.nav || r.sep).map((r) => r.sep
    ? h('div', { class: 'nav-sep' })
    : h('a', { href: '#/' + r.path, class: active === r || (active.path.startsWith('session') && r.path === '') || ((active.path.startsWith('practice/') || active.path.startsWith('lecture')) && r.path === 'practice') ? 'active' : '' }, icon(r.icon), r.nav)));
}

function renderLangSwitch() {
  const el = document.getElementById('lang-switch');
  mount(el, Object.entries(LANGS).map(([code, l]) => h('button', {
    class: state.language === code ? 'active' : '',
    title: `Study ${l.name}`,
    onclick: async () => {
      if (state.language === code) return;
      await saveSettings({ ui: { language: code } });
      applyTheme();
      renderLangSwitch();
      updateBreakLabel();
      const { route } = match(location.hash);
      if (route.path.startsWith('session') || route.path.startsWith('review')) navigate('');
      else render();
    },
  }, h('span', {}, l.flag), l.name)));
}


export async function refreshStatus() {
  const s = await loadStatus();
  const el = document.getElementById('status');
  if (!s) { mount(el, h('div', { class: 'status-line' }, h('span', { class: 'dot bad' }), 'Server not reachable')); return s; }
  const lines = [
    { ok: s.ollama.ok && s.ollama.model_installed, warn: s.ollama.ok && !s.ollama.model_installed, label: s.ollama.ok ? (s.ollama.model_installed ? `LLM · ${s.ollama.model}` : 'LLM · model missing') : 'Ollama offline' },
    { ok: s.stt.available, label: s.stt.available ? `Listening · ${s.stt.backend}` : 'Speech input off', warn: !s.stt.available },
    { ok: ['macos', 'piper'].includes(s.tts.engine), warn: s.tts.engine === 'browser', label: `Voice · ${s.tts.engine}` },
    { ok: s.anki.ok, warn: !s.anki.ok, label: s.anki.ok ? 'Anki connected' : 'Anki not open' },
  ];
  if (s.anki.ok && state.settings?.anki?.auto_add && !pushedPending) {
    pushedPending = true;
    api.post('/api/anki/push-pending', {}).then((r) => { if (r.added?.length) toast(`${r.added.length} queued word(s) sent to Anki`, 'success'); }).catch(() => {});
  }
  mount(el, lines.map((l) => h('div', { class: 'status-line', title: 'Open settings', onclick: () => navigate('settings') },
    h('span', { class: `dot ${l.ok ? 'ok' : l.warn ? 'warn' : 'bad'}` }), l.label)),
    s.demo ? null : h('button', { class: 'btn sm quit-btn', title: 'Show Parlera to others on a temporary copy — nothing is saved', onclick: openDemoDialog }, icon('play', 14), 'Demo mode'),
    h('button', { class: 'btn sm quit-btn', title: s.demo ? 'End the demo and delete its temporary copy' : 'Stop Parlera and free the model\'s memory', onclick: quitApp }, icon('x', 14), s.demo ? 'End demo' : 'Quit Parlera'));
  if (s.demo && !document.getElementById('demo-banner')) showDemoBanner(s.demo);
  return s;
}

// Heartbeat: the server quits by itself a few minutes after the last tab is gone.
function startHeartbeat() {
  let failures = 0;
  const beat = () => fetch('/api/heartbeat', { method: 'POST' })
    .then((r) => r.json())
    .then((j) => {
      failures = 0;
      document.getElementById('server-gone')?.remove();
      // the server was updated while this page was open → reload to get the new version
      const current = document.querySelector('script[type=module]')?.src.match(/v-([0-9a-f]+)/)?.[1];
      if (j.build && current && j.build !== current) location.reload();
    })
    .catch(() => { failures += 1; if (failures >= 2) showServerGone(); });
  beat();
  setInterval(beat, 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) beat(); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) beat(); });
  window.addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye'); } catch { /* ignore */ } });
}

function showServerGone() {
  if (document.getElementById('server-gone')) return;
  document.body.append(h('div', { id: 'server-gone', class: 'overlay' }, h('div', { class: 'overlay-box' },
    h('img', { src: '/static/favicon.svg', width: 56, height: 56, alt: '' }),
    h('h2', {}, 'Parlera is not running'),
    h('div', { class: 'muted' }, 'It was stopped (Quit button, closed tab or Terminal window). Your progress is saved. Start it again with the Parlera app or ./run.sh — this page reconnects by itself.'))));
}

function showDemoBanner(mode) {
  document.body.classList.add('is-demo');
  document.body.prepend(h('div', { id: 'demo-banner', class: 'demo-banner' },
    h('b', {}, 'DEMO MODE'), ` · ${mode === 'fresh' ? 'fresh start' : 'copy of your data'} · nothing you do here is saved — your real progress is untouched`,
    h('button', { class: 'btn sm', onclick: quitApp }, 'End demo')));
}

async function openDemoDialog() {
  const { modal } = await import('./ui.js');
  const choice = await modal({
    title: 'Demo mode',
    body: h('div', { class: 'col' },
      h('p', { class: 'muted' }, 'Opens a second Parlera in its own window that works on a temporary copy. Show it to others, try any feature, change settings or prompts — when the demo ends, the copy is deleted and your real progress, sessions, prompts and settings are exactly as before.'),
      h('div', { class: 'callout' }, icon('info'), h('div', {}, 'Anki is switched off in the demo, so no cards land in your decks. The same language model is used, so the first reply may take a moment.'))),
    actions: [{ label: 'Cancel' }, { label: 'Fresh start', value: 'fresh' }, { label: 'Copy of my data', class: 'primary', value: 'copy' }],
  }).done;
  if (!choice) return;
  toast('Starting the demo…', 'info', 3000);
  try {
    const r = await api.post('/api/demo/start', { mode: choice });
    toast(h('span', {}, 'Demo opened in a new window. If it didn\'t appear: ', h('a', { href: r.url, target: '_blank', style: { color: 'inherit', textDecoration: 'underline' } }, r.url)), 'success', 9000);
  } catch (e) { toast(e.message, 'error', 7000); }
}

async function quitApp() {
  const { confirmDialog } = await import('./ui.js');
  const demo = state.status?.demo;
  const msg = demo ? 'End the demo? Its temporary copy is deleted. Your real data was never changed.'
    : 'Stop Parlera? Everything is already saved, and unfinished sessions can be resumed next time. The language model is unloaded from memory.';
  if (!(await confirmDialog(msg, { title: demo ? 'End demo' : 'Quit Parlera', ok: demo ? 'End demo' : 'Quit' }))) return;
  let r = { ok: false };
  try { r = await api.post('/api/shutdown'); } catch { r = { ok: true }; }
  if (!r.ok) { toast(r.detail || 'Could not stop the server.', 'error', 6000); return; }
  document.body.innerHTML = `<div style="height:100vh;display:grid;place-items:center;font-family:-apple-system,sans-serif;background:var(--bg);color:var(--ink)">
    <div style="text-align:center"><img src="/static/favicon.svg" width="64" height="64" alt=""><h2>${demo ? 'Demo ended' : 'Parlera has stopped'}</h2>
    <p style="color:var(--ink-2)">${demo ? 'The temporary copy was deleted. You can close this window.' : 'Your progress is saved. You can close this tab.'}</p></div></div>`;
}

function updateBreakLabel() {
  const el = document.getElementById('break-label');
  if (el) el.textContent = { sv: 'Fika ☕', fr: 'Pause café ☕', en: 'Tea time ☕' }[state.language] || 'Chat break';
}

async function boot() {
  try {
    await loadSettings();
  } catch (e) {
    mount(document.getElementById('main'), h('div', { class: 'page' }, h('div', { class: 'callout bad' }, 'Cannot reach the Parlera server: ' + e.message)));
    return;
  }
  applyTheme();
  renderLangSwitch();
  window.__parleraBooted = true;
  refreshStatus();
  startHeartbeat();
  const { openTeacherNote } = await import('./views/teachernote.js');
  mount(document.getElementById('sidebar-actions'),
    h('button', { class: 'btn sidebar-action', title: 'Send your teacher a note: focus, behaviour, new words…', onclick: () => openTeacherNote() }, icon('mail', 16), 'Message your teacher'),
    h('button', { class: 'btn sidebar-action', title: 'A relaxed chat without the curriculum', onclick: async () => { const { startSession } = await import('./views/start.js'); startSession({ mode: 'break' }); } }, icon('coffee', 16), h('span', { id: 'break-label' }, 'Chat break')));
  updateBreakLabel();
  setInterval(refreshStatus, 30000);
  window.addEventListener('hashchange', render);
  window.addEventListener('parlera:status', refreshStatus);
  render();
}

window.addEventListener('unhandledrejection', (e) => { console.error(e.reason); toast(e.reason?.message || String(e.reason), 'error'); });
boot();

