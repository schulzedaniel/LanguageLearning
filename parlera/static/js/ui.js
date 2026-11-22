// Tiny DOM + UI toolkit (no framework, no build step).

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...children) { clear(el); append(el, children); return el; }

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------- icons (stroke icons, 24x24 grid) ----------
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
  micOff: '<path d="M3 3l18 18"/><path d="M9 9v2a3 3 0 0 0 5.1 2.1M15 10V6a3 3 0 0 0-5.7-1.3"/><path d="M5 11a7 7 0 0 0 11.6 5.3M19 11a7 7 0 0 1-.6 2.8"/><path d="M12 18v3"/>',
  book: '<path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2"/><path d="M4 19.5A2 2 0 0 0 6 21h13"/>',
  cards: '<rect x="3" y="6" width="14" height="14" rx="2"/><path d="M7 3h12a2 2 0 0 1 2 2v12"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h0a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h0a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>',
  pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  volume: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
  volumeOff: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m23 9-6 6"/><path d="m17 9 6 6"/>',
  turtle: '<path d="M4 15c0-4 3.6-7 8-7s8 3 8 7z"/><path d="M6 15v3M18 15v3M20 13h2"/>',
  translate: '<path d="M4 5h8M8 3v2M10 5c-1 4-3.5 7-6 8.5M6 9c1 2 3 3.5 5 4.5"/><path d="m13 21 4-9 4 9M14.5 18h5"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.8 9.8 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  upload: '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M5 3h14"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  circle: '<circle cx="12" cy="12" r="9"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  arrowLeft: '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"/>',
  school: '<path d="M2 9 12 4l10 5-10 5z"/><path d="M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5"/>',
  theater: '<path d="M4 4h10v6a5 5 0 0 1-10 0z"/><path d="M10 13v1a5 5 0 0 0 10 0V8h-6"/><path d="M7 8h.01M11 8h.01"/>',
  award: '<circle cx="12" cy="9" r="6"/><path d="m8.5 14-1.5 7 5-3 5 3-1.5-7"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  flame: '<path d="M12 22c4 0 7-2.7 7-7 0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-4-2 2-5 5-5 8 0 4.3 3 7 7 7z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 9v5M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  lightbulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  pin: '<path d="M12 17v5"/><path d="M8 3h8l-1 6 3 3v2H6v-2l3-3z"/>',
  folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  hand: '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-5-2.7L3 15.5a1.5 1.5 0 0 1 2.4-1.8L8 16"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  wave: '<path d="M3 12h2M7 8v8M11 5v14M15 8v8M19 11v2"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
};

export function icon(name, size = 18, cls = '') {
  const span = document.createElement('span');
  span.style.display = 'inline-flex';
  span.innerHTML = `<svg class="${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || P.circle}</svg>`;
  return span.firstChild;
}

// ---------- toasts ----------
export function toast(message, type = 'info', ms = 3800) {
  const root = document.getElementById('toasts');
  const el = h('div', { class: `toast ${type}` }, message);
  root.append(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(() => el.remove(), 320); }, ms);
}

// ---------- modal ----------
export function modal({ title, body, actions = [], wide = false, onClose } = {}) {
  const root = document.getElementById('modal-root');
  let resolve;
  const done = new Promise((r) => (resolve = r));
  const close = (value) => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
    onClose && onClose(value);
    resolve(value);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(undefined); };
  const foot = actions.length
    ? h('div', { class: 'modal-foot' }, actions.map((a) => h('button', {
        class: `btn ${a.class || ''}`,
        onclick: async (ev) => {
          if (a.onClick) {
            const btn = ev.currentTarget;
            btn.disabled = true;
            try { const r = await a.onClick(); if (r !== false) close(a.value ?? r); }
            catch (err) { toast(err.message || String(err), 'error'); }
            finally { btn.disabled = false; }
          } else close(a.value);
        },
      }, a.label)))
    : null;
  const box = h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog' },
    h('div', { class: 'modal-head' }, h('h2', {}, title || ''),
      h('button', { class: 'btn ghost icon', onclick: () => close(undefined), title: 'Close' }, icon('x'))),
    h('div', { class: 'modal-body' }, body),
    foot);
  const backdrop = h('div', { class: 'modal-backdrop', onmousedown: (e) => { if (e.target === backdrop) close(undefined); } }, box);
  root.append(backdrop);
  document.addEventListener('keydown', onKey);
  setTimeout(() => box.querySelector('input,textarea,select')?.focus(), 30);
  return { close, done, el: box };
}

export function confirmDialog(message, { title = 'Are you sure?', ok = 'OK', danger = false } = {}) {
  return modal({
    title, body: h('p', { class: 'muted' }, message),
    actions: [{ label: 'Cancel', value: false }, { label: ok, class: danger ? 'danger' : 'primary', value: true }],
  }).done.then((v) => !!v);
}

export function promptDialog(title, { label = '', value = '', placeholder = '', ok = 'Save', multiline = false } = {}) {
  const input = multiline
    ? h('textarea', { placeholder, rows: 4 }, value)
    : h('input', { type: 'text', value, placeholder });
  const m = modal({
    title, body: h('label', { class: 'field' }, label, input),
    actions: [{ label: 'Cancel', value: null }, { label: ok, class: 'primary', onClick: () => input.value }],
  });
  if (!multiline) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') m.close(input.value); });
  return m.done;
}

// ---------- formatting ----------
export function fmtDate(iso, { time = false } = {}) {
  if (!iso) return '';
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date(); yest.setDate(today.getDate() - 1);
  const same = (a, b) => a.toDateString() === b.toDateString();
  let s = same(d, today) ? 'Today' : same(d, yest) ? 'Yesterday'
    : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
  if (time) s += ' · ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return s;
}

export function fmtDuration(sec) {
  sec = Math.round(sec || 0);
  if (sec < 60) return `${sec}s`;
  const m = Math.round(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function progressBar(frac, cls = '') {
  return h('div', { class: `progress ${cls}` }, h('i', { style: { width: `${Math.round(Math.max(0, Math.min(1, frac || 0)) * 100)}%` } }));
}

export function spinner(lg = false) { return h('span', { class: `spinner ${lg ? 'lg' : ''}` }); }
export function loading(text = 'Loading…') { return h('div', { class: 'loading-block' }, spinner(), text); }

export function empty(iconName, text, action) {
  return h('div', { class: 'empty' }, icon(iconName, 40), h('div', {}, text), action ? h('div', { class: 'mt' }, action) : null);
}

export function download(url, body, filename) {
  return fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
    .then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      return r.blob();
    })
    .then((blob) => {
      const a = h('a', { href: URL.createObjectURL(blob), download: filename });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
}

export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
