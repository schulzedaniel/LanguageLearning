// REST helpers + shared app state.

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(url, opts);
  const type = r.headers.get('content-type') || '';
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new Error(detail || `Request failed (${r.status})`);
  }
  if (type.includes('application/json')) return r.json();
  if (type.startsWith('audio/')) return r.arrayBuffer();
  return r.text();
}

export const api = {
  get: (u) => request('GET', u),
  post: (u, b = {}) => request('POST', u, b),
  put: (u, b = {}) => request('PUT', u, b),
  patch: (u, b = {}) => request('PATCH', u, b),
  del: (u) => request('DELETE', u),
};

export const state = {
  settings: null,
  status: null,
  get language() { return this.settings?.ui?.language || 'sv'; },
  listeners: new Set(),
  emit() { this.listeners.forEach((fn) => fn()); },
};

export async function loadSettings() {
  state.settings = await api.get('/api/settings');
  return state.settings;
}

export async function saveSettings(patch) {
  state.settings = await api.put('/api/settings', patch);
  return state.settings;
}

export async function loadStatus() {
  try { state.status = await api.get('/api/status'); } catch { state.status = null; }
  return state.status;
}

export const LANGS = {
  sv: { name: 'Swedish', native: 'Svenska', flag: '🇸🇪', hello: 'Hej', tutor: 'Astrid' },
  fr: { name: 'French', native: 'Français', flag: '🇫🇷', hello: 'Bonjour', tutor: 'Élodie' },
  en: { name: 'English', native: 'English', flag: '🇬🇧', hello: 'Hello', tutor: 'Oliver' },
};

// gender options per language (English nouns have none)
export const GENDERS = { sv: ['en', 'ett'], fr: ['m', 'f'], en: [] };
