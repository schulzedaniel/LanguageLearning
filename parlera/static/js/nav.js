import { state } from './api.js';

// Navigation helpers shared by views (kept separate from app.js to avoid import cycles).
export function navigate(path) { location.hash = '#/' + path; }
export function refreshStatusSoon() { window.dispatchEvent(new Event('parlera:status')); }

export function applyTheme() {
  const root = document.documentElement;
  root.dataset.lang = state.language;
  const theme = state.settings?.ui?.theme || 'auto';
  if (theme === 'auto') delete root.dataset.theme; else root.dataset.theme = theme;
}
