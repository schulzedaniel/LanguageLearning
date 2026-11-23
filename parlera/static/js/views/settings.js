// Settings: learner profile, model, speech, voices, conversation, Anki, data.
import { api, state, saveSettings, loadStatus, LANGS, teacher } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, download, spinner } from '../ui.js';
import { applyTheme, refreshStatusSoon } from '../nav.js';

export default async function settings(main) {
  mount(main, loading());
  const [st, status] = [JSON.parse(JSON.stringify(state.settings)), await loadStatus()];
  const patch = {};
  const set = (path, value) => {
    const keys = path.split('.');
    let o = patch, s = st;
    keys.slice(0, -1).forEach((k) => { o = (o[k] ||= {}); s = (s[k] ||= {}); });
    o[keys.at(-1)] = value; s[keys.at(-1)] = value;
    saveDebounced();
  };
  let timer;
  const saveDebounced = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const p = JSON.parse(JSON.stringify(patch));
      for (const k of Object.keys(patch)) delete patch[k];
      try { await saveSettings(p); applyTheme(); savedNote(); refreshStatusSoon(); } catch (e) { toast(e.message, 'error'); }
    }, 400);
  };
  const saved = h('span', { class: 'small faint' });
  const savedNote = () => { saved.textContent = '✓ Saved'; setTimeout(() => { saved.textContent = ''; }, 1500); };

  const get = (path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), st);
  const text = (path, label, hint, attrs = {}) => h('label', { class: 'field' }, label,
    h('input', { type: attrs.type || 'text', value: get(path) ?? '', placeholder: attrs.placeholder || '', oninput: (e) => set(path, attrs.type === 'number' ? Number(e.target.value) : e.target.value) }),
    hint ? h('span', { class: 'hint' }, hint) : null);
  const select = (path, label, options, hint) => h('label', { class: 'field' }, label,
    h('select', { onchange: (e) => set(path, e.target.value) }, options.map(([v, l]) => h('option', { value: v, selected: String(get(path)) === String(v) }, l))),
    hint ? h('span', { class: 'hint' }, hint) : null);
  const check = (path, label, hint) => h('div', {}, h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!get(path), onchange: (e) => set(path, e.target.checked) }), label),
    hint ? h('div', { class: 'tiny faint', style: { marginLeft: '25px' } }, hint) : null);
  const range = (path, label, min, max, step, fmt) => {
    const out = h('span', { class: 'small' }, fmt(get(path)));
    return h('label', { class: 'field' }, h('span', { class: 'row between' }, label, out),
      h('input', { type: 'range', min, max, step, value: get(path), oninput: (e) => { out.textContent = fmt(Number(e.target.value)); set(path, Number(e.target.value)); } }));
  };
  const section = (id, title, ...children) => h('div', { class: 'card mb', id: `set-${id}` }, h('h3', {}, title), h('div', { class: 'col gap-lg mt' }, ...children));

  // --- LLM ---
  const models = status?.ollama?.models || [];
  const modelOptions = [...new Set([st.llm.model, ...models])].filter(Boolean).map((m) => [m, models.includes(m) ? m : `${m} (not installed)`]);
  const llm = section('llm', 'Language model (Ollama)',
    status?.ollama?.ok ? null : h('div', { class: 'callout bad' }, icon('alert'), h('div', {}, 'Ollama is not reachable at ', h('code', {}, st.llm.base_url), '. Start the Ollama app.')),
    h('div', { class: 'form-grid' },
      select('llm.model', 'Tutor model', modelOptions, 'Recommended on a 48 GB Mac: gemma4:26b (fast, strong multilingual; the -mlx variant is optimised for Apple Silicon), gemma4:31b (a bit stronger, slower).'),
      select('llm.analysis_model', 'Analysis model', [['', 'Same as tutor model'], ...models.map((m) => [m, m])], 'Used after sessions for feedback and flashcards.'),
      text('llm.base_url', 'Ollama URL'),
      text('llm.keep_alive', 'Keep model loaded for', 'e.g. 30m or 2h — avoids slow first replies.'),
      range('llm.temperature', 'Creativity (temperature)', 0, 1.2, 0.05, (v) => v.toFixed(2)),
      text('llm.num_ctx', 'Context window (tokens)', '16384 is plenty for long sessions.', { type: 'number' }),
      text('llm.context_messages', 'Messages sent per turn', 'Older messages are dropped from the prompt (still saved).', { type: 'number' }),
      h('div', {}, check('llm.disable_thinking', 'Disable "thinking" for reasoning models', 'Faster replies with Qwen3/DeepSeek-style models.')),
      h('div', {}, check('llm.exclusive_models', 'Keep only one big model in memory', 'Before a big model loads (e.g. the analysis model), other big models are unloaded, and the analysis model is freed again right after use. Prevents running out of RAM; switching costs a few seconds.')),
      text('llm.big_model_gb', 'Count models from … GB as "big"', 'Smaller models may stay loaded side by side.', { type: 'number' })),
    h('div', { class: 'callout' }, icon('info'), h('div', {}, 'Install a model in Terminal: ', h('code', {}, `ollama pull ${st.llm.model}`))));

  // --- STT ---
  const sttAvail = status?.stt?.backends || {};
  const stt = section('stt', 'Speech recognition (Whisper)',
    h('div', { class: `callout ${status?.stt?.available ? 'good' : 'warn'}` }, icon(status?.stt?.available ? 'checkCircle' : 'alert'),
      h('div', {}, status?.stt?.available ? `Using ${status.stt.backend} · ${status.stt.model}` : 'No Whisper backend installed. On Apple Silicon run: pip install mlx-whisper (setup.sh does this).')),
    h('div', { class: 'form-grid' },
      select('stt.backend', 'Backend', [['auto', 'Automatic'], ['mlx', `mlx-whisper (Apple Silicon)${sttAvail.mlx ? '' : ' – not installed'}`], ['faster', `faster-whisper${sttAvail.faster ? '' : ' – not installed'}`], ['off', 'Off (type only)']]),
      text('stt.model', 'Whisper model', 'mlx-community/whisper-large-v3-turbo is fast and accurate. First use downloads it (~1.6 GB).'),
      text('stt.models.sv', 'Swedish override (optional)', 'e.g. a KB-Whisper model for better Swedish (faster-whisper backend: KBLab/kb-whisper-large).'),
      text('stt.models.fr', 'French override (optional)'),
      text('stt.models.en', 'English override (optional)'),
      h('div', { class: 'full' }, check('stt.pronunciation_hints', 'Pronunciation hints',
        'Words Whisper was unsure about, or heard differently when you repeat a phrase, are underlined and passed to the tutor for a pronunciation tip.')),
      range('stt.confidence_threshold', 'Flag words recognised below', 0.2, 0.9, 0.05, (v) => `${Math.round(v * 100)}% confidence`),
      select('stt.default_input_language', 'Default "I speak…" setting', [['target', 'The language I study'], ['en', 'English'], ['auto', 'Detect automatically']], 'You can switch this during a session. "Target" gives the best recognition of learner speech.')));

  // --- TTS ---
  const engines = status?.tts?.engines || {};
  const voicesBox = h('div', { class: 'col' });
  const tts = section('tts', 'Tutor voice',
    h('div', { class: 'form-grid' },
      select('tts.engine', 'Voice engine', [['auto', `Automatic (now: ${status?.tts?.engine || '?'})`], ['macos', `macOS voices${engines.macos ? '' : ' – not available'}`], ['piper', `Piper neural voices${engines.piper ? '' : ' – no voices downloaded'}`], ['kokoro', `Kokoro natural voices${engines.kokoro ? '' : ' – not installed'}`], ['browser', 'Browser voices'], ['off', 'Off']], 'Default for all languages; override per language below.'),
      range('tts.speed', 'Speaking speed', 0.6, 1.4, 0.05, (v) => `${Math.round(v * 100)}%`),
      check('tts.beginner_slowdown', 'Speak the target language slower at A1/A2'),
      check('tts.speak_corrections', 'Read corrections (✏️) aloud')),
    voicesBox);
  renderVoices(voicesBox, st, set, status);

  // --- conversation ---
  const conv = section('conv', 'Conversation',
    h('div', { class: 'form-grid' },
      select('conversation.input_mode', 'Default input', [['handsfree', 'Hands-free (voice activity detection)'], ['ptt', 'Push to talk'], ['text', 'Text']]),
      range('conversation.silence_ms', 'Pause before I answer', 600, 3500, 100, (v) => `${(v / 1000).toFixed(1)} s`),
      select('conversation.immersion', 'How much the tutor speaks the target language', [['auto', 'Automatic: mostly target language, rising with your level (A1 ≈ 50–70%)'], ...[25, 40, 50, 60, 75, 85, 95, 100].map((n) => [String(n), `${n}%`])]),
      h('div', { class: 'col' },
        check('conversation.barge_in', 'Let me interrupt the tutor by speaking', 'Works best with headphones (otherwise the tutor may hear itself).'),
        check('conversation.show_text', 'Show the tutor\'s text', 'Turn off for listening practice — reveal each message with a click.'),
        check('conversation.correct_native', 'Correct my English in Swedish and French sessions', 'Off: the teacher only corrects your Swedish/French. Either way, if speech recognition turns your French into odd "English", the teacher asks you to repeat instead of correcting it.'),
        check('conversation.auto_translate', 'Show a translation under every teacher message', 'Handy at the beginning. Each translation is one extra call to the language model. You can always press Translate, or select part of a message to translate just that.'))));

  // --- learner ---
  const learner = section('learner', 'About you',
    h('div', { class: 'form-grid' },
      text('learner.name', 'Your name', 'The tutor will use it.'),
      text('learner.native_language', 'Explanation language', 'The language the tutor uses for explanations in the Swedish and French courses.'),
      h('div', { class: 'full' }, text('learner.goals.sv', '🇸🇪 Swedish goal')),
      h('div', { class: 'full' }, text('learner.goals.fr', '🇫🇷 French goal')),
      h('div', { class: 'full' }, text('learner.goals.en', '🇬🇧 English goal')),
      select('ui.theme', 'Appearance', [['auto', 'Match system'], ['light', 'Light'], ['dark', 'Dark']])));

  // --- teachers ---
  const teacherRow = (lang) => {
    const t = teacher(lang);
    const avatar = h('div', { class: 'avatar' }, t.name[0]);
    return h('div', { class: 'teacher-row' },
      avatar, h('div', { class: 'small', style: { minWidth: '90px' } }, `${LANGS[lang].flag} ${LANGS[lang].name}`),
      h('input', { type: 'text', value: get(`teachers.${lang}.name`) || t.name, placeholder: t.name, 'aria-label': `${LANGS[lang].name} teacher's name`,
        oninput: (e) => { set(`teachers.${lang}.name`, e.target.value.trim()); avatar.textContent = (e.target.value.trim() || '?')[0]; } }),
      h('select', { 'aria-label': `${LANGS[lang].name} teacher's gender`, onchange: (e) => {
        set(`teachers.${lang}.gender`, e.target.value);
        // a new gender → let every engine pick a matching voice again
        for (const eng of ['macos', 'piper', 'kokoro', 'browser']) set(`tts.voices.${eng}.${lang}`, '');
        toast(`Voice for ${LANGS[lang].name} reset to automatic — it now picks a ${e.target.value} voice.`, 'info', 4000);
        setTimeout(() => renderVoices(voicesBox, st, set, status), 500);
      } }, [['female', 'Woman · female voice'], ['male', 'Man · male voice']].map(([v, l]) => h('option', { value: v, selected: t.gender === v }, l))));
  };
  const teachers = section('teachers', 'Your teachers',
    h('div', { class: 'small muted' }, 'Name your teachers and choose who they are. The name is used everywhere (greeting, prompts, feedback), and the voice follows the gender automatically — unless you pick a specific voice under "Tutor voice". Their personality and teaching style live in Teacher prompts → Persona.'),
    h('div', { class: 'col' }, ['sv', 'fr', 'en'].map(teacherRow)));

  // --- curriculum & vocab ---
  const prog = section('progress', 'Progress & flashcards',
    h('div', { class: 'form-grid' },
      range('curriculum.advance_threshold', 'Mastery needed to move on', 0.5, 0.95, 0.05, (v) => `${Math.round(v * 100)}%`),
      h('div', {}, check('curriculum.auto_advance', 'Move to the next unit automatically', 'Otherwise you get a "Move on" button.')),
      text('vocab.max_cards_per_session', 'Max. flashcards suggested per session', '', { type: 'number' }),
      h('div', {}, check('vocab.reinforce', 'Reinforce recently learned words', 'The tutor subtly reuses words you added in the last weeks — more often for young cards, rarely for mature ones.')),
      text('vocab.reinforce_count', 'Words offered to the tutor per session', 'It uses two or three of them naturally.', { type: 'number' }),
      text('workshop.interval_days', 'Mistake workshop every … days', 'The dashboard suggests a workshop when it is due.', { type: 'number' }),
      text('workshop.min_mistakes', 'Only if at least … new mistakes', '', { type: 'number' }),
      h('div', { class: 'full' }, check('workshop.thinking', 'Let the model think while preparing the workshop', 'Better grouping and explanations with reasoning models (Gemma 4, Muse Glimmer, Qwen 3); takes longer. Live conversation never uses thinking.')),
      range('vocab.min_zipf', 'Skip rare words below frequency', 0, 4, 0.5, (v) => (v === 0 ? 'off' : `Zipf ${v}`)),
      text('practice.round_length', 'Questions per practice game', 'Practice → Quick games.', { type: 'number' }),
      text('history.archive_after_days', 'Archive sessions after … days without activity', '0 = never. Archived sessions stay complete and can be resumed (Sessions → Archive).', { type: 'number' }),
      h('div', {}, check('practice.lecture_thinking', 'Let the model think while writing grammar lectures', 'Deeper, more accurate explanations with reasoning models; takes a minute or two.'))));

  // --- anki ---
  const deckList = h('datalist', { id: 'anki-decks' });
  api.get('/api/anki/decks').then((r) => mount(deckList, ...r.decks.map((d) => h('option', { value: d })))).catch(() => {});
  const deckField = (lang, label) => h('label', { class: 'field' }, label,
    h('input', { type: 'text', list: 'anki-decks', value: get(`anki.decks.${lang}`) || '', placeholder: `Parlera::${LANGS[lang].name}`,
      oninput: (e) => set(`anki.decks.${lang}`, e.target.value) }),
    h('span', { class: 'hint' }, 'Pick one of your existing decks or type a new name (use :: for sub-decks).'));
  const ankiStatus = h('div', { class: `callout ${status?.anki?.ok ? 'good' : 'warn'}` }, icon(status?.anki?.ok ? 'checkCircle' : 'info'),
    h('div', {}, status?.anki?.ok ? `Connected to AnkiConnect (v${status.anki.version}).`
      : ['Open Anki and install the ', h('b', {}, 'AnkiConnect'), ' add-on (Tools → Add-ons → Get Add-ons → code ', h('code', {}, '2055492159'), '), then restart Anki.']));
  const anki = section('anki', 'Anki',
    ankiStatus, deckList,
    h('div', { class: 'form-grid' },
      deckField('sv', '🇸🇪 Swedish deck'),
      deckField('fr', '🇫🇷 French deck'),
      deckField('en', '🇬🇧 English deck'),
      h('div', { class: 'full' }, check('anki.auto_add', 'Add new words to Anki automatically after each session',
        'You can still remove single cards on the review page. If Anki is closed, words are queued and sent next time it\'s open.')),
      text('anki.url', 'AnkiConnect URL'),
      check('anki.deck_per_unit', 'One sub-deck per unit'),
      check('anki.add_reverse', 'Also create English → target cards'),
      check('anki.include_audio', 'Add pronunciation audio to cards', 'Uses the macOS/Piper voice.'),
      check('anki.auto_sync', 'Use Anki review data to pick words for sessions')),
    h('div', {}, h('button', { class: 'btn sm', onclick: async () => {
      try { const r = await api.get('/api/anki/test'); toast(`AnkiConnect v${r.version} · ${r.decks.length} decks`, 'success'); } catch (e) { toast(e.message, 'error', 7000); }
    } }, 'Test connection')));

  // --- general / quitting ---
  // window / offline status (filled asynchronously)
  const sysBox = h('div', { class: 'col' });
  api.get('/api/system').then((sys) => {
    const fmtModels = sys.models.map((m) => `${m.repo} ${m.downloaded ? '✓ downloaded' : '— downloads on first use (needs internet once)'}`);
    mount(sysBox,
      h('div', { class: `callout ${sys.app_browser ? 'good' : ''}` }, icon(sys.app_browser ? 'checkCircle' : 'info'),
        h('div', {}, sys.app_browser ? `App window available via ${sys.app_browser.split('/').pop().replace('.app', '')}.`
          : ['No Chrome, Edge or Brave found, so Parlera opens in a normal tab. In Safari you can make your own app window: open Parlera, then ', h('b', {}, 'File → Add to Dock'), '.'])),
      h('div', { class: `callout ${sys.offline?.offline ? 'good' : 'warn'}` }, icon(sys.offline?.offline ? 'checkCircle' : 'info'),
        h('div', {}, h('b', {}, sys.offline?.offline ? 'Running fully offline. ' : 'Online check active. '),
          fmtModels.length ? fmtModels.join(' · ') : 'No downloadable models needed.')));
  }).catch(() => {});

  const general = section('general', 'Starting & quitting',
    h('div', { class: 'form-grid' },
      h('div', {}, check('app.auto_quit', 'Stop Parlera automatically when I close the browser tab', 'About 45 seconds after the last Parlera tab is closed, the server stops and the model is unloaded. Reloading the page is fine.')),
      text('app.idle_quit_minutes', 'Also stop if no tab was seen for … minutes', 'Safety net for tabs that were never closed properly. Browsers pause hidden tabs, so keep this generous.', { type: 'number' }),
      select('app.quit_ollama', 'Quit Ollama when Parlera stops', [['if_started', 'Only if Parlera started it (recommended)'], ['always', 'Always (also if it was already running)'], ['never', 'Never']],
        'The model itself is always unloaded, freeing its memory. The idle Ollama app uses almost nothing.'),
      select('app.window', 'Open Parlera in', [['auto', 'Its own app window if possible (recommended)'], ['app', 'Its own app window (Chrome / Edge / Brave)'], ['browser', 'A normal browser tab']],
        'App window: no tabs or address bar, and closing it stops Parlera. Needs Chrome, Edge or Brave installed (Parlera uses its own private profile there). Takes effect at the next start.'),
      select('app.offline', 'Internet use', [['auto', 'Offline once all models are downloaded (recommended)'], ['always', 'Always offline (never download)']],
        'Ollama, Whisper, voices and Anki all run locally. Internet is only needed to download models the first time.')),
    sysBox,
    h('div', { class: 'small faint' }, 'You can also stop Parlera any time with "Quit Parlera" at the bottom of the sidebar.'));

  // --- data ---
  const fileInput = h('input', { type: 'file', accept: '.zip', class: 'hidden', onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (!(await confirmDialog('Restore this backup? Your current data will be replaced (a safety copy is kept in the backups folder).', { danger: true, ok: 'Restore' }))) return;
    const fd = new FormData(); fd.append('file', f);
    try { await api.post('/api/restore', fd); toast('Backup restored', 'success'); setTimeout(() => location.reload(), 800); } catch (err) { toast(err.message, 'error'); }
  } });
  const settingsInput = h('input', { type: 'file', accept: '.json', class: 'hidden', onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try { await api.post('/api/settings/import', fd); toast('Settings imported', 'success'); setTimeout(() => location.reload(), 600); } catch (err) { toast(err.message, 'error'); }
  } });
  const cacheBox = h('div', { class: 'col' });
  const fmtBytes = (b) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b >= 1e3 ? `${Math.round(b / 1e3)} KB` : `${b} B`);
  async function renderCache() {
    let sys;
    try { sys = await api.get('/api/system'); } catch { return; }
    const rows = Object.entries(sys.cache).map(([key, c]) => h('div', { class: 'list-item' },
      h('div', { class: 'grow' }, h('div', {}, c.label), h('div', { class: 'tiny faint' }, c.hint)),
      h('b', { class: 'small' }, fmtBytes(c.bytes)),
      c.readonly ? h('span', { class: 'tiny faint', style: { width: '64px' } }, 'kept') : h('button', { class: 'btn sm', disabled: !c.bytes, onclick: async () => {
        const r = await api.post('/api/cache/clear', { targets: [key] }); toast(`Freed ${fmtBytes(r.freed)}`, 'success'); renderCache();
      } }, 'Clear')));
    mount(cacheBox, h('div', { class: 'card flat', style: { padding: '4px 14px' } }, h('div', { class: 'list' }, rows)),
      h('div', { class: 'row wrap' },
        h('button', { class: 'btn', onclick: async () => {
          const r = await api.post('/api/cache/clear', { targets: ['tts', 'media', 'old_backups', 'browser'] });
          toast(`Freed ${fmtBytes(r.freed)}`, 'success'); renderCache();
        } }, icon('trash', 15), 'Clear all caches'),
        h('button', { class: 'btn ghost', title: 'Forgets this browser\'s small UI preferences (panel, situation preset) and reloads the page', onclick: () => {
          try { localStorage.clear(); sessionStorage.clear(); } catch { /* ignore */ }
          if ('caches' in window) caches.keys().then((ks) => ks.forEach((k) => caches.delete(k)));
          location.reload();
        } }, icon('refresh', 15), 'Reset page & reload')),
      h('div', { class: 'tiny faint' }, 'Clearing caches never deletes your progress, words, sessions or settings.'));
  }
  const data = section('data', 'Your data',
    h('div', { class: 'kv' }, h('dt', {}, 'Data folder'), h('dd', {}, h('code', {}, status?.data_dir || '?')),
      h('dt', {}, 'Contains'), h('dd', { class: 'small muted' }, 'parlera.db (sessions, progress, words, memories), settings.json, prompts/, curricula/, backups/ (daily automatic copies)')),
    h('div', { class: 'row wrap' },
      h('button', { class: 'btn', onclick: () => download('/api/backup', null, `parlera-backup-${new Date().toISOString().slice(0, 10)}.zip`) }, icon('download', 16), 'Download backup'),
      h('button', { class: 'btn', onclick: () => fileInput.click() }, icon('upload', 16), 'Restore backup…'), fileInput),
    h('div', { class: 'section-label' }, 'Settings'),
    h('div', { class: 'small muted' }, 'Your settings (models, voices, Anki decks, …) live in settings.json in your data folder. Updates never touch it, a previous copy is kept next to it, and daily copies go to backups/. If the file ever gets damaged, the last good copy is used automatically.'),
    h('div', { class: 'row wrap' },
      h('button', { class: 'btn', onclick: () => download('/api/settings/export', null, `parlera-settings-${new Date().toISOString().slice(0, 10)}.json`) }, icon('download', 16), 'Export settings'),
      h('button', { class: 'btn', onclick: () => settingsInput.click() }, icon('upload', 16), 'Import settings…'), settingsInput),
    h('div', { class: 'section-label' }, 'Storage & cache'),
    cacheBox,
    h('div', { class: 'small faint' }, `Parlera v${status?.version || ''} · everything stays on this computer.`));
  renderCache();

  const navItems = [['learner', 'About you'], ['teachers', 'Your teachers'], ['general', 'Starting & quitting'], ['llm', 'Language model'], ['stt', 'Speech recognition'], ['tts', 'Tutor voice'], ['conv', 'Conversation'], ['progress', 'Progress & cards'], ['anki', 'Anki'], ['data', 'Your data']];
  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Settings'), h('div', { class: 'sub' }, 'Changes save automatically.')), saved),
    h('div', { class: 'settings-grid' },
      h('nav', { class: 'settings-nav' }, navItems.map(([id, label]) => h('a', { href: '#', onclick: (e) => { e.preventDefault(); document.getElementById(`set-${id}`).scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, label))),
      h('div', {}, learner, teachers, general, llm, stt, tts, conv, prog, anki, data))));
  return () => clearTimeout(timer);
}

const ENGINE_LABEL = { macos: 'macOS', piper: 'Piper', kokoro: 'Kokoro (natural)', browser: 'Browser', off: 'Off' };
const KOKORO_LANGS = new Set(['en', 'fr']);

// Per-language voice setup: engine override + voice for that engine + test button.
async function renderVoices(box, st, set, status) {
  mount(box, spinner());
  const engines = status?.tts?.engines || {};
  const [macVoices, piperCat, kokoroVoices] = await Promise.all([
    engines.macos ? api.get('/api/tts/voices?engine=macos').catch(() => ({})) : {},
    api.get('/api/tts/piper/catalog').catch(() => ({ voices: [] })),
    api.get('/api/tts/voices?engine=kokoro').catch(() => ({})),
  ]);
  const defaultEngine = st.tts.engine === 'auto' ? status?.tts?.engine : st.tts.engine;
  const effective = (l) => (st.tts.engines?.[l] || defaultEngine);
  const browserVoices = 'speechSynthesis' in window ? speechSynthesis.getVoices() : [];

  const test = async (lang) => {
    try {
      if (effective(lang) === 'browser') {
        const samples = { sv: 'Hej! Välkommen till din svensklektion.', fr: 'Bonjour ! Bienvenue à ton cours de français.', en: 'Hello! Shall we practise together?' };
        const u = new SpeechSynthesisUtterance(samples[lang]); u.lang = { sv: 'sv-SE', fr: 'fr-FR', en: 'en-GB' }[lang];
        const v = browserVoices.find((x) => x.name === st.tts.voices.browser?.[lang]); if (v) u.voice = v;
        speechSynthesis.speak(u); return;
      }
      toast('Generating sample… (the first Kokoro sample downloads the model, ~330 MB)', 'info', 2500);
      const buf = await api.post('/api/tts/test', { lang });
      const ctx = new AudioContext(); const src = ctx.createBufferSource(); src.buffer = await ctx.decodeAudioData(buf); src.connect(ctx.destination); src.start();
    } catch (e) { toast(e.message, 'error', 7000); }
  };

  const G = (g) => (g === 'female' ? ' · ♀' : g === 'male' ? ' · ♂' : '');
  const row = (lang, label) => {
    const eng = effective(lang);
    const auto = `Automatic (${teacher(lang).gender} voice for ${teacher(lang).name})`;
    const engineOpts = [['', `Default (${ENGINE_LABEL[defaultEngine] || defaultEngine})`],
      ...['macos', 'kokoro', 'piper', 'browser'].filter((e) => e !== 'kokoro' || KOKORO_LANGS.has(lang))
        .map((e) => [e, `${ENGINE_LABEL[e]}${e === 'browser' || engines[e] ? '' : ' – not installed'}`])];
    let voiceSel;
    if (eng === 'macos') {
      voiceSel = h('select', { onchange: (e) => set(`tts.voices.macos.${lang}`, e.target.value) }, h('option', { value: '' }, auto),
        (macVoices[lang] || []).map((v) => h('option', { value: v.name, selected: st.tts.voices.macos?.[lang] === v.name }, `${v.name} · ${v.locale}${G(v.gender)}`)));
    } else if (eng === 'kokoro') {
      voiceSel = h('select', { onchange: (e) => set(`tts.voices.kokoro.${lang}`, e.target.value) }, h('option', { value: '' }, auto),
        (kokoroVoices[lang] || []).map((v) => h('option', { value: v.name, selected: (st.tts.voices.kokoro?.[lang] || '') === v.name }, `${v.name} – ${v.desc}`)));
    } else if (eng === 'piper') {
      voiceSel = h('select', { onchange: (e) => set(`tts.voices.piper.${lang}`, e.target.value) }, h('option', { value: '' }, auto),
        piperCat.voices.filter((v) => v.lang === lang).map((v) => h('option', { value: v.name, selected: st.tts.voices.piper?.[lang] === v.name }, `${v.name} – ${v.desc}${v.installed ? '' : ' (not downloaded)'}`)));
    } else if (eng === 'browser') {
      voiceSel = h('select', { onchange: (e) => set(`tts.voices.browser.${lang}`, e.target.value) }, h('option', { value: '' }, auto),
        browserVoices.filter((v) => v.lang.toLowerCase().startsWith(lang)).map((v) => h('option', { value: v.name, selected: st.tts.voices.browser?.[lang] === v.name }, `${v.name} (${v.lang})`)));
    } else voiceSel = h('select', { disabled: true }, h('option', {}, '—'));
    return h('div', { class: 'card flat', style: { padding: '12px 14px' } },
      h('div', { class: 'row between' }, h('b', {}, label), h('button', { class: 'btn sm', onclick: () => test(lang) }, icon('play', 14), 'Test')),
      h('div', { class: 'form-grid mt' },
        h('label', { class: 'field' }, 'Engine', h('select', { onchange: async (e) => { set(`tts.engines.${lang}`, e.target.value); st.tts.engines = { ...(st.tts.engines || {}), [lang]: e.target.value }; setTimeout(() => renderVoices(box, st, set, status), 500); } },
          engineOpts.map(([v, l]) => h('option', { value: v, selected: (st.tts.engines?.[lang] || '') === v }, l)))),
        h('label', { class: 'field' }, 'Voice', voiceSel)));
  };

  mount(box,
    h('div', { class: 'callout' }, icon('lightbulb'), h('div', {},
      h('b', {}, 'Most natural: '), 'Kokoro for English and French (re-run ./setup.sh and answer "y" to natural voices). Swedish: macOS ',
      h('i', {}, 'Alva (Premium)'), ' (System Settings → Accessibility → Spoken Content → Manage Voices).')),
    row('en', '🇬🇧 English (English course + explanations)'), row('fr', '🇫🇷 French'), row('sv', '🇸🇪 Swedish'),
    piperCat.installed_package ? h('details', {}, h('summary', { class: 'small', style: { cursor: 'pointer' } }, 'Download Piper voices'),
      h('div', { class: 'row wrap mt' }, piperCat.voices.map((v) => h('button', { class: 'btn sm', disabled: v.installed, onclick: async (e) => {
        const b = e.currentTarget; b.disabled = true; mount(b, spinner(), ` ${v.name}`);
        try { await api.post('/api/tts/piper/download', { name: v.name }); toast(`${v.name} downloaded`, 'success'); renderVoices(box, st, set, await loadStatus()); }
        catch (err) { toast(err.message, 'error'); b.disabled = false; mount(b, v.name); }
      } }, v.installed ? icon('check', 13) : icon('download', 13), v.name)))) : null);
}
