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

const ROUTES = [
  { path: '', view: dashboard, nav: 'Home', icon: 'home' },
  { path: 'curriculum', view: curriculum, nav: 'Curriculum', icon: 'book' },
  { path: 'vocab', view: vocab, nav: 'Vocabulary', icon: 'cards' },
  { path: 'history', view: history, nav: 'Sessions', icon: 'clock' },
  { path: 'memory', view: memory, nav: 'Memory', icon: 'brain' },
  { sep: true },
  { path: 'prompts', view: prompts, nav: 'Teacher prompts', icon: 'pen' },
  { path: 'settings', view: settings, nav: 'Settings', icon: 'gear' },
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
    : h('a', { href: '#/' + r.path, class: active === r || (active.path.startsWith('session') && r.path === '') ? 'active' : '' }, icon(r.icon), r.nav)));
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
    h('span', { class: `dot ${l.ok ? 'ok' : l.warn ? 'warn' : 'bad'}` }), l.label)));
  return s;
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
  refreshStatus();
  setInterval(refreshStatus, 30000);
  window.addEventListener('hashchange', render);
  window.addEventListener('parlera:status', refreshStatus);
  render();
}

window.addEventListener('unhandledrejection', (e) => { console.error(e.reason); toast(e.reason?.message || String(e.reason), 'error'); });
boot();

