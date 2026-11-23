// Settings: learner profile, model, speech, voices, conversation, Anki, data.
import { api, state, saveSettings, loadStatus, LANGS } from '../api.js';
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
      h('div', {}, check('llm.disable_thinking', 'Disable "thinking" for reasoning models', 'Faster replies with Qwen3/DeepSeek-style models.'))),
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
      select('tts.engine', 'Voice engine', [['auto', `Automatic (now: ${status?.tts?.engine || '?'})`], ['macos', `macOS voices${engines.macos ? '' : ' – not available'}`], ['piper', `Piper neural voices${engines.piper ? '' : ' – no voices downloaded'}`], ['browser', 'Browser voices'], ['off', 'Off']]),
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
        check('conversation.show_text', 'Show the tutor\'s text', 'Turn off for listening practice — reveal each message with a click.'))));

  // --- learner ---
  const learner = section('learner', 'About you',
    h('div', { class: 'form-grid' },
      text('learner.name', 'Your name', 'The tutor will use it.'),
      text('learner.native_language', 'Explanation language', 'The language the tutor uses for explanations in the Swedish and French courses.'),
      h('div', { class: 'full' }, text('learner.goals.sv', '🇸🇪 Swedish goal')),
      h('div', { class: 'full' }, text('learner.goals.fr', '🇫🇷 French goal')),
      h('div', { class: 'full' }, text('learner.goals.en', '🇬🇧 English goal')),
      select('ui.theme', 'Appearance', [['auto', 'Match system'], ['light', 'Light'], ['dark', 'Dark']])));

  // --- curriculum & vocab ---
  const prog = section('progress', 'Progress & flashcards',
    h('div', { class: 'form-grid' },
      range('curriculum.advance_threshold', 'Mastery needed to move on', 0.5, 0.95, 0.05, (v) => `${Math.round(v * 100)}%`),
      h('div', {}, check('curriculum.auto_advance', 'Move to the next unit automatically', 'Otherwise you get a "Move on" button.')),
      text('vocab.max_cards_per_session', 'Max. flashcards suggested per session', '', { type: 'number' }),
      h('div', {}, check('vocab.reinforce', 'Reinforce recently learned words', 'The tutor subtly reuses words you added in the last weeks — more often for young cards, rarely for mature ones.')),
      text('vocab.reinforce_count', 'Words offered to the tutor per session', 'It uses two or three of them naturally.', { type: 'number' }),
      range('vocab.min_zipf', 'Skip rare words below frequency', 0, 4, 0.5, (v) => (v === 0 ? 'off' : `Zipf ${v}`))));

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

  // --- data ---
  const fileInput = h('input', { type: 'file', accept: '.zip', class: 'hidden', onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (!(await confirmDialog('Restore this backup? Your current data will be replaced (a safety copy is kept in the backups folder).', { danger: true, ok: 'Restore' }))) return;
    const fd = new FormData(); fd.append('file', f);
    try { await api.post('/api/restore', fd); toast('Backup restored', 'success'); setTimeout(() => location.reload(), 800); } catch (err) { toast(err.message, 'error'); }
  } });
  const data = section('data', 'Your data',
    h('div', { class: 'kv' }, h('dt', {}, 'Data folder'), h('dd', {}, h('code', {}, status?.data_dir || '?')),
      h('dt', {}, 'Contains'), h('dd', { class: 'small muted' }, 'parlera.db (sessions, progress, words, memories), settings.json, prompts/, curricula/, backups/ (daily automatic copies)')),
    h('div', { class: 'row wrap' },
      h('button', { class: 'btn', onclick: () => download('/api/backup', null, `parlera-backup-${new Date().toISOString().slice(0, 10)}.zip`) }, icon('download', 16), 'Download backup'),
      h('button', { class: 'btn', onclick: () => fileInput.click() }, icon('upload', 16), 'Restore backup…'), fileInput),
    h('div', { class: 'small faint' }, `Parlera v${status?.version || ''} · everything stays on this computer.`));

  const navItems = [['learner', 'About you'], ['llm', 'Language model'], ['stt', 'Speech recognition'], ['tts', 'Tutor voice'], ['conv', 'Conversation'], ['progress', 'Progress & cards'], ['anki', 'Anki'], ['data', 'Your data']];
  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Settings'), h('div', { class: 'sub' }, 'Changes save automatically.')), saved),
    h('div', { class: 'settings-grid' },
      h('nav', { class: 'settings-nav' }, navItems.map(([id, label]) => h('a', { href: '#', onclick: (e) => { e.preventDefault(); document.getElementById(`set-${id}`).scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, label))),
      h('div', {}, learner, llm, stt, tts, conv, prog, anki, data))));
  return () => clearTimeout(timer);
}

async function renderVoices(box, st, set, status) {
  const engine = st.tts.engine === 'auto' ? status?.tts?.engine : st.tts.engine;
  const test = async (lang) => {
    try {
      if (engine === 'browser') {
        const samples = { sv: 'Hej! Välkommen till din svensklektion.', fr: 'Bonjour ! Bienvenue à ton cours de français.', en: 'Hi! Let\'s practise together.' };
        const u = new SpeechSynthesisUtterance(samples[lang]); u.lang = { sv: 'sv-SE', fr: 'fr-FR', en: 'en-US' }[lang];
        const v = speechSynthesis.getVoices().find((x) => x.name === st.tts.voices.browser?.[lang]); if (v) u.voice = v;
        speechSynthesis.speak(u); return;
      }
      const buf = await api.post('/api/tts/test', { lang });
      const ctx = new AudioContext(); const src = ctx.createBufferSource(); src.buffer = await ctx.decodeAudioData(buf); src.connect(ctx.destination); src.start();
    } catch (e) { toast(e.message, 'error'); }
  };
  const langs = [['sv', '🇸🇪 Swedish'], ['fr', '🇫🇷 French'], ['en', '🇬🇧 English (explanations + English course)']];
  if (engine === 'macos') {
    mount(box, spinner());
    const voices = await api.get('/api/tts/voices?engine=macos');
    mount(box, 
      h('div', { class: 'callout' }, icon('lightbulb'), h('div', {}, h('b', {}, 'Get much better voices for free: '),
        'System Settings → Accessibility → Spoken Content → System voice → Manage Voices… → download e.g. ', h('i', {}, 'Alva (Premium)'), ' / ', h('i', {}, 'Klara'), ' for Swedish and ', h('i', {}, 'Thomas'), ' / ', h('i', {}, 'Audrey (Premium)'), ' for French. Then reload this page.')),
      h('div', { class: 'form-grid' }, langs.map(([l, label]) => h('div', { class: 'row', style: { alignItems: 'flex-end' } },
        h('label', { class: 'field grow' }, label, h('select', { onchange: (e) => set(`tts.voices.macos.${l}`, e.target.value) },
          h('option', { value: '' }, 'Best available (automatic)'),
          (voices[l] || []).map((v) => h('option', { value: v.name, selected: st.tts.voices.macos?.[l] === v.name }, `${v.name} · ${v.locale}`)))),
        h('button', { class: 'btn icon', title: 'Test', onclick: () => test(l) }, icon('play', 15))))));
  } else if (engine === 'piper' || st.tts.engine === 'piper') {
    const cat = await api.get('/api/tts/piper/catalog');
    mount(box, 
      cat.installed_package ? null : h('div', { class: 'callout warn' }, icon('alert'), h('div', {}, 'Install Piper first: ', h('code', {}, 'pip install piper-tts'))),
      h('div', { class: 'form-grid' }, langs.map(([l, label]) => h('div', { class: 'row', style: { alignItems: 'flex-end' } },
        h('label', { class: 'field grow' }, label, h('select', { onchange: (e) => set(`tts.voices.piper.${l}`, e.target.value) },
          cat.voices.filter((v) => v.lang === l).map((v) => h('option', { value: v.name, selected: st.tts.voices.piper?.[l] === v.name }, `${v.name} – ${v.desc}${v.installed ? '' : ' (not downloaded)'}`)))),
        h('button', { class: 'btn icon', title: 'Test', onclick: () => test(l) }, icon('play', 15))))),
      h('div', { class: 'section-label' }, 'Download voices'),
      h('div', { class: 'row wrap' }, cat.voices.map((v) => h('button', { class: 'btn sm', disabled: v.installed, onclick: async (e) => {
        const b = e.currentTarget; b.disabled = true; mount(b, spinner(), ` ${v.name}`);
        try { await api.post('/api/tts/piper/download', { name: v.name }); toast(`${v.name} downloaded`, 'success'); renderVoices(box, st, set, await loadStatus()); }
        catch (err) { toast(err.message, 'error'); b.disabled = false; mount(b, v.name); }
      } }, v.installed ? icon('check', 13) : icon('download', 13), v.name))));
  } else if (engine === 'browser') {
    const all = speechSynthesis.getVoices();
    mount(box, 
      h('div', { class: 'callout warn' }, icon('info'), 'Browser voices work for conversation, but flashcard audio needs the macOS or Piper engine.'),
      h('div', { class: 'form-grid' }, langs.map(([l, label]) => h('div', { class: 'row', style: { alignItems: 'flex-end' } },
        h('label', { class: 'field grow' }, label, h('select', { onchange: (e) => set(`tts.voices.browser.${l}`, e.target.value) },
          h('option', { value: '' }, 'Automatic'), all.filter((v) => v.lang.toLowerCase().startsWith(l)).map((v) => h('option', { value: v.name, selected: st.tts.voices.browser?.[l] === v.name }, `${v.name} (${v.lang})`)))),
        h('button', { class: 'btn icon', onclick: () => test(l) }, icon('play', 15))))));
  } else {
    mount(box);
  }
}
