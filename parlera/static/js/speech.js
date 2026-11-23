// Play a word or sentence aloud outside a session (Practice, lectures).
// Uses the server voice for that language; falls back to the browser's speechSynthesis.
import { api, state, teacher } from './api.js';
import { voiceGender } from './audio.js';

const BROWSER_LANG = { sv: 'sv-SE', fr: 'fr-FR', en: 'en-GB' };
let ctx = null;
let current = null;
let engines = null;   // per-language TTS engine, asked once per page load

export async function say(text, lang = state.language, { rate = 1 } = {}) {
  text = String(text || '').replace(/\*\*/g, '').trim();
  if (!text) return;
  try { current?.stop(); } catch { /* ignore */ }
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  engines ||= api.get('/api/tts/engines').then((r) => r.per_language || {}).catch(() => ({}));
  const server = ['macos', 'piper', 'kokoro'].includes((await engines)[lang]);
  try {
    if (!server) throw new Error('browser voice');
    const buf = await api.post('/api/speak', { text, language: lang, mixed: false, lang, rate });
    ctx ||= new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') await ctx.resume();
    const audio = await ctx.decodeAudioData(buf);
    const src = ctx.createBufferSource();
    src.buffer = audio; src.connect(ctx.destination); src.start();
    current = src;
  } catch {
    if (!('speechSynthesis' in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = BROWSER_LANG[lang] || lang;
    u.rate = rate;
    const g = teacher(lang).gender;
    const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(lang));
    const pref = state.settings?.tts?.voices?.browser?.[lang];
    u.voice = voices.find((v) => v.name === pref) || voices.find((v) => voiceGender(v.name) === g) || voices[0] || null;
    speechSynthesis.speak(u);
  }
}
