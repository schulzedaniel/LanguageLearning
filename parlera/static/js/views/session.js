// Live conversation: voice (hands-free or push-to-talk) or text, streaming replies with speech.
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, modal, fmtDuration, fmtDate, spinner, escapeHtml } from '../ui.js';
import { renderMarkdown } from '../markdown.js';
import { Recorder, Player, b64FromBuffer, bufferFromB64 } from '../audio.js';
import { navigate } from '../nav.js';
import { addWordDialog } from './vocab.js';

const MODE_ICON = { lesson: 'school', conversation: 'chat', roleplay: 'theater', review: 'refresh', exam: 'award', writing: 'pen', placement: 'compass', free: 'sparkle', pronunciation: 'wave', workshop: 'target', break: 'coffee' };

export default async function session(main, { id }) {
  mount(main, loading('Opening session…'));
  const s = await api.get(`/api/sessions/${id}`);
  if (s.language !== state.language) {
    // keep the UI language in sync with the session we open
    const { saveSettings } = await import('../api.js');
    await saveSettings({ ui: { language: s.language } });
    document.documentElement.dataset.lang = s.language;
  }
  const lang = s.language;
  const L = LANGS[lang];
  const conv = state.settings.conversation || {};
  const isWriting = s.mode === 'writing';

  // ---------------- state ----------------
  let inputMode = isWriting ? 'text' : (conv.input_mode || 'handsfree');
  let sttLang = state.settings.stt?.default_input_language || 'target';
  let audioOn = !isWriting;
  let showText = conv.show_text !== false;
  let showPanel = localStorage.getItem('parlera.panel') !== '0' && s.mode !== 'break';
  const BREAK_NAME = { sv: 'Fika', fr: 'Pause café', en: 'Tea time' }[lang] || 'Chat break';
  let ws = null;
  let started = false;
  let awaitingReply = false;
  let current = null;           // assistant message being streamed
  let pendingUser = null;       // placeholder bubble while transcribing
  let ttsMode = 'server';
  let closed = false;
  let phase = 'idle';
  const startTime = Date.now();
  const usedTerms = new Set();

  // ---------------- audio ----------------
  const player = new Player({
    voices: state.settings.tts?.voices?.browser || {},
    speaker: s.language, gender: LANGS[s.language]?.tutorGender,
    onStart: (meta) => { setPhase('speaking'); meta?.el?.classList.add('speaking'); updatePause(); },
    onIdle: () => { document.querySelectorAll('.msg.speaking').forEach((e) => e.classList.remove('speaking')); updatePause(); refreshPhase(); },
  });
  const recorder = new Recorder({
    silenceMs: conv.silence_ms || 1400,
    onLevel: (rms) => { ring.style.opacity = recorder.state === 'off' ? 0 : Math.min(1, rms * 18); ring.style.transform = `scale(${1 + Math.min(0.35, rms * 6)})`; },
    onSpeechStart: () => {
      if (player.busy && conv.barge_in) { player.stop(); send({ type: 'interrupt' }); }
      setPhase('recording');
    },
    onUtterance: (wav) => sendAudio(wav),
    onState: () => refreshPhase(),
  });
  recorder.bargeIn = !!conv.barge_in;
  recorder.mode = inputMode === 'text' ? 'off' : inputMode;

  function updatePause() { recorder.setPaused(awaitingReply || player.busy); }

  // ---------------- DOM ----------------
  const chatInner = h('div', { class: 'chat-inner' });
  const chat = h('div', { class: 'chat' }, chatInner);
  chat.addEventListener('mouseup', () => setTimeout(selectionPopover, 10));
  chat.addEventListener('scroll', () => document.querySelector('.sel-translate')?.remove());
  const dropSel = (e) => { if (!e.target.closest?.('.sel-translate')) document.querySelector('.sel-translate')?.remove(); };
  document.addEventListener('mousedown', dropSel);
  const ring = h('span', { class: 'ring' });
  const micBtn = h('button', { class: 'mic off', title: 'Microphone' }, ring, icon('mic', 26));
  const micStatus = h('div', { class: 'mic-status' });
  const mono = lang === 'en';
  const textInput = h('textarea', { rows: 1, placeholder: isWriting ? 'Write your text here… (Enter to send, Shift+Enter for a new line)' : mono ? 'Type your answer… (Enter to send)' : `Type in ${L.name} or English… (Enter to send)` });
  const sendBtn = h('button', { class: 'btn primary icon', title: 'Send', onclick: () => sendText() }, icon('send', 18));
  const timerEl = h('span', { class: 'timer' });

  // Situation presets: how you talk and how the tutor answers
  const SITUATIONS = {
    full: { label: '🗣 Talk & listen', input: null, audio: true },
    nospeak: { label: '⌨️ Can\'t speak — I type, tutor talks', input: 'text', audio: true },
    nolisten: { label: '🔇 Can\'t listen — I talk, tutor writes', input: 'voice', audio: false },
    silent: { label: '🤫 Silent — type & read', input: 'text', audio: false },
  };
  const situationSel = h('select', { title: 'Your situation', style: { width: 'auto', padding: '6px 10px', fontSize: '13px', fontWeight: 600 },
    onchange: (e) => applySituation(e.target.value) },
  Object.entries(SITUATIONS).map(([k, v]) => h('option', { value: k }, v.label)));
  function applySituation(key, initial = false) {
    const sit = SITUATIONS[key] || SITUATIONS.full;
    situationSel.value = key;
    try { localStorage.setItem('parlera.situation', key); } catch { /* ignore */ }
    if (sit.input === 'text') { if (initial) inputMode = 'text'; else setInputMode('text'); }
    else if (inputMode === 'text') { const v = conv.input_mode && conv.input_mode !== 'text' ? conv.input_mode : 'handsfree'; if (initial) inputMode = v; else setInputMode(v); }
    if (audioOn !== sit.audio) { if (initial) audioOn = sit.audio; else toggleAudio(); }
    if (!sit.audio && !showText && !initial) toggleText();
    if (!sit.audio && initial) showText = true;
  }

  const modeSeg = seg([
    ['handsfree', 'Hands-free', 'wave'], ['ptt', 'Push to talk', 'hand'], ['text', 'Text', 'keyboard'],
  ], inputMode, (v) => setInputMode(v));
  const langSeg = seg([
    ['target', `I speak ${L.name}`], ['en', 'English'], ['auto', 'Auto'],
  ], sttLang, (v) => { sttLang = v; });
  if (!isWriting) { let sk = 'full'; try { sk = localStorage.getItem('parlera.situation') || 'full'; } catch { /* ignore */ } applySituation(sk, true); modeSeg.set(inputMode); recorder.mode = inputMode === 'text' ? 'off' : inputMode; }
  const audioBtn = h('button', { class: 'btn ghost sm', title: 'Tutor voice on/off', onclick: () => toggleAudio() });
  const textBtn = h('button', { class: 'btn ghost sm', title: 'Show/hide tutor text (listening practice)', onclick: () => toggleText() });
  const helpBtn = h('button', { class: 'btn ghost sm', title: mono ? 'Say it better' : 'How do I say…?', onclick: () => helpSay() }, icon('translate', 16), mono ? 'Say it better…' : 'How do I say…?');

  const micRow = h('div', { class: 'mic-wrap' }, micBtn, micStatus);
  const textRow = h('div', { class: 'composer-row' }, textInput, sendBtn);
  const composer = h('div', { class: 'composer' }, h('div', { class: 'composer-inner' },
    h('div', { class: 'composer-controls' }, h('div', { class: 'row wrap' }, isWriting ? null : situationSel, isWriting ? null : modeSeg, isWriting || mono ? null : langSeg),
      h('div', { class: 'row' }, helpBtn, audioBtn, textBtn)),
    micRow, textRow));

  const panel = buildPanel(s);
  const top = h('div', { class: 'session-top' },
    h('button', { class: 'btn ghost icon', title: 'Save & leave', onclick: () => leave() }, icon('arrowLeft')),
    h('span', { class: 'badge accent' }, icon(MODE_ICON[s.mode] || 'chat', 13), s.mode === 'break' ? BREAK_NAME : (s.mode_info?.title || s.mode)),
    h('div', { class: 'title grow' }, s.mode === 'break' ? `${BREAK_NAME} with ${L.tutor}` : s.mode === 'workshop' ? s.title : s.unit ? `${s.unit.level} · ${s.unit.title}` : s.title),
    timerEl,
    h('button', { class: 'btn ghost icon', title: 'Toggle side panel', onclick: () => { showPanel = !showPanel; localStorage.setItem('parlera.panel', showPanel ? '1' : '0'); layout.classList.toggle('no-panel', !showPanel); } }, icon('panel')),
    h('button', { class: 'btn sm', onclick: () => leave() }, 'Save & exit'),
    h('button', { class: 'btn sm primary', onclick: () => endSession() }, icon('check', 15), 'End & review'));

  const layout = h('div', { class: `session ${showPanel ? '' : 'no-panel'}` },
    h('div', { class: 'session-main' }, top, chat, composer), panel.el);
  mount(main, layout);

  // existing messages (resumed session)
  // dividers show when the session was started and each time you came back to it
  const GAP_MS = 20 * 60 * 1000;
  const divider = (text) => chatInner.append(h('div', { class: 'chat-divider' }, h('span', {}, text)));
  let prevTs = null;
  for (const m of s.messages) {
    const ts = new Date(m.created_at).getTime();
    if (prevTs === null) divider(`Started ${fmtDate(m.created_at, { time: true })}`);
    else if (ts - prevTs > GAP_MS) divider(`Continued ${fmtDate(m.created_at, { time: true })}`);
    prevTs = ts;
    addMessage(m.role, m.content, { id: m.id, final: true, pron: m.meta?.pron });
  }
  if (prevTs !== null && Date.now() - prevTs > GAP_MS) divider('Now · continuing where you left off');
  if (s.messages.length) markUsed();

  // start gate: a click is needed to unlock audio playback and the microphone
  const gate = h('div', { class: 'card center', style: { alignSelf: 'center', marginTop: s.messages.length ? '10px' : '12vh', maxWidth: '440px' } },
    h('div', { class: 'avatar', style: { width: '56px', height: '56px', fontSize: '22px', margin: '0 auto 12px' } }, L.tutor[0]),
    h('h2', {}, s.messages.length ? `Continue with ${L.tutor}` : `${L.hello}! I'm ${L.tutor}.`),
    s.messages.length ? h('p', { class: 'small', style: { margin: '6px 0 0' } }, `You're continuing the session you started ${fmtDate(s.created_at, { time: true })} (${((n) => `${n} turn${n === 1 ? '' : 's'}`)(s.messages.filter((m) => m.role === 'user').length)} so far). ${L.tutor} remembers everything and picks up where you stopped.`)
      : h('p', { class: 'small faint', style: { margin: '6px 0 0' } }, 'A new session.'),
    h('p', { class: 'muted mt' }, isWriting ? 'This is a writing session — you type, I correct.'
      : inputMode === 'handsfree' ? 'Hands-free: just talk. I\'ll answer when you pause. Use headphones for the best experience.'
        : inputMode === 'ptt' ? 'Hold the mic button (or the space bar) while you speak.' : 'Type your answers below.'),
    h('button', { class: 'btn primary lg mt', onclick: () => begin() }, icon(isWriting || inputMode === 'text' ? 'play' : 'mic', 18), s.messages.length ? 'Continue' : 'Start'));
  chatInner.append(gate);
  scrollDown();
  refreshControls();

  async function begin() {
    gate.remove();
    player.ensureContext();
    if (inputMode !== 'text') await startMic();
    connect();
  }

  // ---------------- websocket ----------------
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/sessions/${s.id}`);
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'settings', audio: audioOn }));
      ws.send(JSON.stringify({ type: 'start', resume: true }));
      started = true;
      if (!s.messages.length) { awaitingReply = true; updatePause(); }
    };
    ws.onmessage = (ev) => onServer(JSON.parse(ev.data));
    ws.onclose = () => {
      if (closed) return;
      toast('Connection lost — reconnecting…', 'error', 2500);
      setTimeout(() => { if (!closed) connect(); }, 1500);
    };
  }

  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  function onServer(m) {
    switch (m.type) {
      case 'ready': ttsMode = m.tts; break;
      case 'transcribing': setPhase('transcribing'); break;
      case 'transcript':
        if (m.empty) {
          pendingUser?.el.remove(); pendingUser = null;
          awaitingReply = false; updatePause(); refreshPhase();
          toast("I didn't catch that — try again.", 'info', 2000);
        } else {
          if (pendingUser) { pendingUser.set(m.text, m.pron); pendingUser = null; } else addMessage('user', m.text, { final: true, pron: m.pron });
          markUsed();
        }
        break;
      case 'assistant_start':
        awaitingReply = true; updatePause();
        current = addMessage('assistant', '', { streaming: true });
        if (audioOn && ttsMode !== 'off') player.openStream();
        setPhase('thinking');
        break;
      case 'token':
        if (current) current.append(m.text);
        break;
      case 'audio':
        if (audioOn) player.enqueueWav(bufferFromB64(m.data), { el: current?.el || lastAssistant() });
        break;
      case 'speak':
        if (audioOn) player.enqueueSpeech(m.segments, m.rates, { el: current?.el || lastAssistant() });
        if (m.fallback) console.warn('TTS fallback:', m.fallback);
        break;
      case 'assistant_end':
        if (current) { current.finish(m.message_id, m.content, m.failed); current = null; }
        awaitingReply = false;
        if (!audioOn || ttsMode === 'off') player.endStream();
        updatePause(); refreshPhase();
        break;
      case 'audio_end': player.endStream(); break;
      case 'error': toast(m.message, 'error', 6000); break;
      default: break;
    }
  }

  // ---------------- input ----------------
  async function startMic() {
    try {
      recorder.mode = inputMode;
      await recorder.start();
      micBtn.classList.remove('off');
    } catch (e) {
      toast('Microphone not available: ' + e.message, 'error');
      setInputMode('text');
    }
    refreshPhase();
  }

  function sendAudio(wav) {
    if (!started) return;
    if (player.busy) { player.stop(); send({ type: 'interrupt' }); }
    pendingUser = addMessage('user', '', { pending: true });
    awaitingReply = true; updatePause();
    send({ type: 'user_audio', data: b64FromBuffer(wav), lang: sttLang });
    setPhase('transcribing');
  }

  function sendText() {
    const text = textInput.value.trim();
    if (!text) return;
    if (!started) { begin().then(() => setTimeout(() => sendTextNow(text), 400)); textInput.value = ''; return; }
    sendTextNow(text);
    textInput.value = ''; autoGrow();
  }

  function sendTextNow(text) {
    if (player.busy) player.stop();
    addMessage('user', text, { final: true });
    markUsed();
    awaitingReply = true; updatePause();
    send({ type: 'user_text', text });
    setPhase('thinking');
  }

  function setInputMode(v) {
    inputMode = v;
    modeSeg.set(v);
    if (v === 'text') { recorder.stop(); micBtn.classList.add('off'); }
    else if (started || recorder.ctx) { recorder.setMode(v); if (!recorder.ctx) startMic(); }
    else recorder.mode = v;
    refreshControls(); refreshPhase();
  }

  function toggleAudio() {
    audioOn = !audioOn;
    if (!audioOn) player.stop();
    send({ type: 'settings', audio: audioOn });
    refreshControls();
  }

  function toggleText() {
    showText = !showText;
    chatInner.querySelectorAll('.msg.assistant .bubble').forEach((b) => b.classList.toggle('blurred', !showText));
    refreshControls();
  }

  // mic button: toggle (hands-free) or hold (push-to-talk)
  micBtn.addEventListener('click', async () => {
    if (inputMode !== 'handsfree') return;
    if (!started) { await begin(); return; }
    if (recorder.state === 'off') await startMic();
    else { recorder.stop(); micBtn.classList.add('off'); refreshPhase(); }
  });
  const pttDown = async (e) => {
    if (inputMode !== 'ptt') return;
    e.preventDefault();
    if (!started) { await begin(); return; }
    if (!recorder.ctx) await startMic();
    if (player.busy) { player.stop(); send({ type: 'interrupt' }); }
    recorder.setPaused(false);
    recorder.pttStart();
    micBtn.classList.add('recording');
  };
  const pttUp = () => {
    if (inputMode !== 'ptt' || !recorder.recording) return;
    recorder.pttStop();
    micBtn.classList.remove('recording');
  };
  micBtn.addEventListener('mousedown', pttDown);
  micBtn.addEventListener('touchstart', pttDown, { passive: false });
  window.addEventListener('mouseup', pttUp);
  window.addEventListener('touchend', pttUp);

  const onKey = (e) => {
    const typing = ['TEXTAREA', 'INPUT', 'SELECT'].includes(document.activeElement?.tagName);
    if (e.key === 'Escape' && player.busy) { player.stop(); send({ type: 'interrupt' }); }
    if (e.code === 'Space' && !typing && inputMode === 'ptt') {
      e.preventDefault();
      if (e.type === 'keydown' && !e.repeat) pttDown(e);
      if (e.type === 'keyup') pttUp();
    }
  };
  window.addEventListener('keydown', onKey);
  window.addEventListener('keyup', onKey);

  textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); }
  });
  const autoGrow = () => { textInput.style.height = 'auto'; textInput.style.height = Math.min(160, textInput.scrollHeight) + 'px'; };
  textInput.addEventListener('input', autoGrow);

  // ---------------- status line ----------------
  function setPhase(p) { phase = p; renderStatus(); }
  function refreshPhase() {
    if (awaitingReply && !player.busy) phase = phase === 'transcribing' ? 'transcribing' : 'thinking';
    else if (player.busy && player.playing) phase = 'speaking';
    else if (recorder.state === 'speaking') phase = 'recording';
    else phase = 'idle';
    renderStatus();
  }
  function renderStatus() {
    micBtn.classList.toggle('recording', phase === 'recording');
    const off = recorder.state === 'off';
    const msgs = {
      recording: [h('b', {}, 'Listening…'), ' pause to send'],
      transcribing: [spinner(), ' Understanding…'],
      thinking: [spinner(), ` ${L.tutor} is thinking…`],
      speaking: [h('b', {}, `${L.tutor} is speaking`), ' · Esc to stop'],
      idle: inputMode === 'handsfree'
        ? (off ? ['Microphone off — click to talk'] : [h('b', {}, 'Your turn'), ' — just speak'])
        : inputMode === 'ptt' ? [h('b', {}, 'Hold to talk'), ' (or hold ', h('kbd', {}, 'Space'), ')'] : [],
    };
    mount(micStatus, ...(msgs[phase] || []));
  }

  function refreshControls() {
    micRow.classList.toggle('hidden', inputMode === 'text');
    mount(audioBtn, icon(audioOn ? 'volume' : 'volumeOff', 16));
    mount(textBtn, icon(showText ? 'eye' : 'eyeOff', 16));
    renderStatus();
  }

  // ---------------- messages ----------------
  function addMessage(role, content, { id = null, final = false, streaming = false, pending = false, pron = null } = {}) {
    const body = h('div', { class: 'content' });
    const bubble = h('div', { class: 'bubble' }, body);
    const actions = h('div', { class: 'msg-actions' });
    const el = h('div', { class: `msg ${role}` }, h('div', { class: 'avatar' }, role === 'user' ? ((state.settings.learner?.name || 'You')[0].toUpperCase()) : L.tutor[0]), bubble, actions);
    let text = content || '';
    let raf = 0;
    const render = () => {
      raf = 0;
      if (role === 'assistant') body.innerHTML = text ? renderMarkdown(text) : '<span class="typing"><i></i><i></i><i></i></span>';
      else body.innerHTML = userHtml(text, pron);
      if (pending && !text) body.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    };
    render();
    if (role === 'assistant' && !showText) {
      bubble.classList.add('blurred');
    }
    bubble.addEventListener('click', (e) => {
      if (bubble.classList.contains('blurred')) { bubble.classList.remove('blurred'); return; }
      const tl = e.target.closest('strong.tl');
      if (tl) wordPopover(tl, tl.dataset.tl, text);
    });
    chatInner.append(el);
    scrollDown();
    const api_ = {
      el,
      append(t) { text += t; if (!raf) raf = requestAnimationFrame(() => { render(); scrollDown(); }); },
      set(t, p) { text = t; if (p) pron = p; render(); scrollDown(); },
      finish(mid, full, failed) {
        if (full !== undefined && full !== null && full !== '') text = full;
        if (failed && !text) { el.remove(); return; }
        render(); addActions(mid);
        if (role === 'assistant' && !mono && state.settings.conversation?.auto_translate && text.trim()) translate(bubble, text, { auto: true });
      },
    };
    function addActions(mid) {
      if (role !== 'assistant') return;
      mount(actions, 
        h('button', { class: 'btn ghost icon sm', title: 'Play again', onclick: () => replay(text, false, el) }, icon('volume', 15)),
        h('button', { class: 'btn ghost icon sm', title: 'Play slowly', onclick: () => replay(text, true, el) }, icon('turtle', 15)),
        h('button', { class: 'btn ghost sm translate-btn', title: mono ? 'Explain (paraphrase + difficult words). Tip: select part of a message to explain just that.' : 'Translate this message. Tip: select part of a message to translate just that.', onclick: () => translate(bubble, text) }, icon('translate', 15), mono ? 'Explain' : 'Translate'));
    }
    if (final) addActions(id);
    return api_;
  }

  function lastAssistant() { const all = chatInner.querySelectorAll('.msg.assistant'); return all[all.length - 1]; }
  function scrollDown() { requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; }); }

  async function replay(text, slow, el) {
    player.stop();
    player.ensureContext();
    try {
      if (ttsMode === 'server') {
        const wav = await api.post('/api/speak', { text, language: lang, slow });
        player.enqueueWav(wav, { el });
      } else {
        const { segments } = await api.post('/api/segments', { text, language: lang });
        const r = slow ? { [lang]: 0.7, en: 1 } : {};
        player.enqueueSpeech(segments, r, { el });
      }
    } catch (e) { toast(e.message, 'error'); }
  }

  async function translate(bubble, text, { auto = false } = {}) {
    const existing = bubble.querySelector('.translation');
    if (existing) { if (!auto) existing.remove(); return; }
    const box = h('div', { class: 'translation' }, spinner());
    bubble.append(box);
    try {
      const r = await api.post('/api/translate', { text, language: lang, direction: 'to_native' });
      mount(box, r.text);
    } catch (e) { mount(box, 'Translation failed: ' + e.message); }
    scrollDown();
  }

  function wordPopover(anchor, word, context) {
    document.querySelector('.popover')?.remove();
    const rect = anchor.getBoundingClientRect();
    const meaning = h('div', { class: 'small muted pop-meaning' }, spinner(), ' ');
    const pop = h('div', { class: 'popover', style: { left: `${Math.min(window.innerWidth - 260, rect.left)}px`, top: `${rect.bottom + 6}px` } },
      h('div', { class: 'w' }, word), meaning,
      h('div', { class: 'row' },
        h('button', { class: 'btn sm', onclick: () => sayWord(word) }, icon('volume', 14), 'Listen'),
        h('button', { class: 'btn sm', onclick: () => { pop.remove(); addWordDialog(lang, word, context, s.id); } }, icon('plus', 14), 'Add card')));
    document.body.append(pop);
    const close = (e) => { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener('mousedown', close); } };
    setTimeout(() => document.addEventListener('mousedown', close), 0);
    meaningOf(word, context).then((m) => mount(meaning, m)).catch(() => meaning.remove());
  }

  // meaning of a word/phrase as used in the teacher's sentence (cached per session)
  const meanings = new Map();
  function meaningOf(text, context) {
    const key = `${text}\u0000${context}`;
    if (!meanings.has(key)) {
      const sentence = (String(context).replace(/\*\*/g, '').split(/(?<=[.!?])\s+/).find((x) => x.includes(text.replace(/\*\*/g, ''))) || context).slice(0, 400);
      meanings.set(key, api.post('/api/translate', { text, context: sentence, language: lang, direction: 'to_native' }).then((r) => r.text));
    }
    return meanings.get(key);
  }

  // select part of a teacher message → translate just that
  function selectionPopover() {
    document.querySelector('.sel-translate')?.remove();
    const sel = window.getSelection();
    const picked = sel && !sel.isCollapsed ? sel.toString().trim() : '';
    if (!picked || picked.length > 400) return;
    const bubbleEl = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement)?.closest('.msg.assistant .bubble');
    if (!bubbleEl || bubbleEl.classList.contains('blurred')) return;
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const context = bubbleEl.querySelector('.content')?.innerText || '';
    const btn = h('button', { class: 'btn sm primary sel-translate', style: { left: `${Math.max(8, Math.min(window.innerWidth - 150, rect.left + rect.width / 2 - 60))}px`, top: `${Math.max(8, rect.top - 40)}px` },
      onmousedown: (e) => e.preventDefault(),
      onclick: async () => {
        btn.remove();
        const pop = h('div', { class: 'popover', style: { left: `${Math.min(window.innerWidth - 300, Math.max(8, rect.left))}px`, top: `${rect.bottom + 6}px`, maxWidth: '300px' } },
          h('div', { class: 'w' }, picked), h('div', { class: 'small muted pop-meaning' }, spinner()),
          h('div', { class: 'row' },
            h('button', { class: 'btn sm', onclick: () => sayWord(picked) }, icon('volume', 14), 'Listen'),
            !mono && picked.split(/\s+/).length <= 4 ? h('button', { class: 'btn sm', onclick: () => { pop.remove(); addWordDialog(lang, picked, context, s.id); } }, icon('plus', 14), 'Add card') : null));
        document.body.append(pop);
        const close = (e) => { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener('mousedown', close); } };
        setTimeout(() => document.addEventListener('mousedown', close), 0);
        const out = pop.querySelector('.pop-meaning');
        try { mount(out, await meaningOf(picked, context)); } catch (e) { mount(out, `Translation failed: ${e.message}`); }
      } }, icon('translate', 14), mono ? 'Explain' : 'Translate');
    document.body.append(btn);
  }

  async function sayWord(word) {
    player.stop(); player.ensureContext();
    try {
      if (ttsMode === 'server') player.enqueueWav(await api.post('/api/speak', { text: word, language: lang, mixed: false, lang, slow: true }));
      else player.enqueueSpeech([{ lang, text: word }], { [lang]: 0.75 });
    } catch (e) { toast(e.message, 'error'); }
  }

  async function helpSay() {
    const input = h('input', { type: 'text', placeholder: 'e.g. "I would like a coffee with milk"' });
    const result = h('div', { class: 'mt' });
    const m = modal({
      title: mono ? 'Say it better' : `How do I say it in ${L.name}?`,
      body: h('div', {}, h('label', { class: 'field' }, mono ? 'Write what you want to say (in any language, or plain English) and get a polished C1 version:' : 'What do you want to say (in English)?', input), result),
      actions: [{ label: 'Close' }, { label: 'Translate', class: 'primary', onClick: async () => { await go(); return false; } }],
    });
    async function go() {
      if (!input.value.trim()) return;
      mount(result, spinner());
      const r = await api.post('/api/translate', { text: input.value, language: lang, direction: 'to_target' });
      mount(result, h('div', { class: 'card flat' },
        h('div', { style: { fontSize: '18px', fontWeight: 650, color: 'var(--tl)' } }, r.text),
        h('div', { class: 'row mt' },
          h('button', { class: 'btn sm', onclick: () => sayWord(r.text) }, icon('volume', 14), 'Listen'),
          h('button', { class: 'btn sm', onclick: () => { textInput.value = r.text; m.close(); textInput.focus(); autoGrow(); } }, icon('edit', 14), 'Put in text box'))));
    }
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  }

  // ---------------- panel ----------------
  function markUsed() {
    const userText = ' ' + [...chatInner.querySelectorAll('.msg.user .content')].map((e) => e.textContent.toLowerCase()).join(' \n ') + ' ';
    for (const chip of panel.chips) {
      const terms = chip.dataset.term.toLowerCase().split(/[,/]| – /)
        .map((t) => t.replace(/^(en|ett|le|la|les|un|une|l')\s+/, '').replace(/[()…?!.]/g, '').trim()).filter((t) => t.length > 1);
      const hit = terms.some((t) => new RegExp(`(^|[^\\p{L}])${t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^\\p{L}]|$)`, 'u').test(userText));
      if (hit) { chip.classList.add('used'); usedTerms.add(chip.dataset.term); }
    }
    panel.count.textContent = `${usedTerms.size}/${panel.chips.length} used`;
  }

  function buildPanel(sess) {
    const u = sess.unit;
    const chips = [];
    const count = h('span', { class: 'tiny faint' });
    if (sess.mode === 'break') {
      return { chips, count, el: h('aside', { class: 'panel' }, h('div', { class: 'card' }, h('h4', {}, BREAK_NAME),
        h('div', { class: 'small muted' }, 'A relaxed chat: no curriculum, only light corrections. Press "End & review" if you want feedback and flashcards from it; otherwise just leave.'))) };
    }
    if (sess.workshop) {
      const w = sess.workshop;
      return { chips, count, el: h('aside', { class: 'panel' },
        h('div', { class: 'card' }, h('h4', {}, 'Workshop'), h('div', { style: { fontWeight: 650 } }, w.title), h('div', { class: 'small muted mt', html: renderMarkdown(w.overview || '') })),
        w.categories.map((c, i) => h('div', { class: 'card' },
          h('h4', {}, `${i + 1}. ${c.name}`),
          h('div', { class: 'small', html: renderMarkdown(c.rule) }),
          c.examples?.length ? h('div', { class: 'mt' }, c.examples.map((e) => h('div', { class: 'small', style: { margin: '4px 0' } },
            h('span', { class: 'wrong-inline' }, e.wrong), ' → ', h('b', { style: { color: 'var(--good)' } }, e.right)))) : null,
          c.tip ? h('div', { class: 'goal mt' }, icon('lightbulb', 14), h('span', { html: renderMarkdown(c.tip).replace(/<\/?p>/g, '') })) : null))) };
    }
    if (!u) {
      return { el: h('aside', { class: 'panel' }, h('div', { class: 'card' }, h('h4', {}, 'Session'), h('div', { class: 'small muted' }, sess.mode_info?.description || ''))), chips, count };
    }
    const vocabChips = u.vocab_pairs.map((p) => {
      const c = h('span', { class: 'chip', title: p.meaning, dataset: { term: p.term } }, p.term);
      chips.push(c);
      return c;
    });
    const el = h('aside', { class: 'panel' },
      sess.scenario ? h('div', { class: 'card' }, h('h4', {}, 'Scenario'), h('div', { class: 'small' }, sess.scenario)) : null,
      sess.focus ? h('div', { class: 'card' }, h('h4', {}, 'Your focus'), h('div', { class: 'small' }, sess.focus)) : null,
      u.can_do.length ? h('div', { class: 'card' }, h('h4', {}, 'Goals'), u.can_do.map((g) => h('div', { class: 'goal' }, icon('target', 14), g))) : null,
      vocabChips.length ? h('div', { class: 'card' }, h('div', { class: 'row between' }, h('h4', {}, 'Key words'), count), h('div', { class: 'chips' }, vocabChips)) : null,
      u.phrase_pairs.length ? h('div', { class: 'card' }, h('h4', {}, 'Useful phrases'),
        u.phrase_pairs.map((p) => h('div', { class: 'phrase', title: 'Click to listen', onclick: () => sayWord(p.term.replace(/…/g, '')) }, h('span', { class: 't' }, p.term), h('span', { class: 'm' }, p.meaning)))) : null,
      u.grammar.length ? h('div', { class: 'card' }, h('h4', {}, 'Grammar'), u.grammar.map((g) => h('div', { class: 'goal' }, icon('lightbulb', 14), g))) : null,
      u.culture ? h('div', { class: 'card' }, h('h4', {}, 'Culture'), h('div', { class: 'small muted' }, u.culture)) : null,
      h('div', { class: 'card' }, h('h4', {}, 'Tips'),
        h('div', { class: 'small muted col', style: { gap: '4px' } },
          h('div', {}, 'Click a ', h('b', { style: { color: 'var(--tl)' } }, 'highlighted word'), ' to hear it or make a flashcard.'),
          h('div', {}, h('kbd', {}, 'Esc'), ' stops the tutor speaking.'),
          h('div', {}, 'Hide the text (', icon('eye', 12), ') for listening practice.'),
          h('div', {}, 'Say "slower please" or switch to English anytime.'))));
    return { el, chips, count };
  }

  // ---------------- timer ----------------
  const timer = setInterval(() => { timerEl.textContent = fmtDuration((s.duration || 0) + (Date.now() - startTime) / 1000); }, 1000);
  timerEl.textContent = fmtDuration(s.duration || 0);

  // ---------------- leaving ----------------
  function teardown() {
    document.removeEventListener('mousedown', dropSel);
    document.querySelector('.sel-translate')?.remove();
    closed = true;
    clearInterval(timer);
    try { ws?.close(); } catch { /* ignore */ }
    recorder.stop();
    player.stop();
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('keyup', onKey);
    window.removeEventListener('mouseup', pttUp);
    window.removeEventListener('touchend', pttUp);
    document.querySelector('.popover')?.remove();
    // don't keep sessions that never got going
    if (!chatInner.querySelector('.msg')) api.del(`/api/sessions/${s.id}`).catch(() => {});
  }

  async function leave() {
    const userTurns = chatInner.querySelectorAll('.msg.user').length;
    if (userTurns >= 2) {
      const choice = await modal({
        title: 'Leave this session?',
        body: h('div', {}, h('p', { class: 'muted' }, 'Everything is saved. Review it now (feedback, mistakes, flashcards, progress), or keep it open to continue later from Sessions.'),
          h('p', { class: 'small faint' }, 'Flashcards and feedback are only created when you press End & review.')),
        actions: [{ label: 'Cancel', value: 'cancel' }, { label: 'Keep for later', value: 'later' }, { label: 'End & review now', class: 'primary', value: 'review' }],
      }).done;
      if (!choice || choice === 'cancel') return;
      if (choice === 'review') { await endSession(true); return; }
    }
    toast('Session saved. Resume it any time from Sessions.', 'success');
    navigate('');
  }

  async function endSession(skipConfirm = false) {
    const userTurns = chatInner.querySelectorAll('.msg.user').length;
    if (!userTurns) {
      if (await confirmDialog('You haven\'t said anything yet, so there is nothing to review. Delete this empty session?', { ok: 'Delete', danger: true })) {
        await api.del(`/api/sessions/${s.id}`);
        navigate('');
      }
      return;
    }
    if (!skipConfirm && !(await confirmDialog(`${L.tutor} will review the session: feedback, mistakes, progress on the unit, and flashcard suggestions. This takes up to a minute.`, { title: 'End session & review?', ok: 'End & review' }))) return;
    player.stop(); recorder.stop();
    const steps = h('div', { class: 'steps' },
      h('div', {}, '• Summarising the session'), h('div', {}, '• Collecting your mistakes'), h('div', {}, '• Updating your unit progress'), h('div', {}, '• Picking flashcards for Anki'));
    const overlay = h('div', { class: 'overlay' }, h('div', { class: 'overlay-box' }, spinner(true), h('h2', {}, 'Reviewing your session…'), steps));
    document.body.append(overlay);
    try {
      await api.post(`/api/sessions/${s.id}/end`);
      overlay.remove();
      navigate(`review/${s.id}`);
    } catch (e) {
      overlay.remove();
      toast('Review failed: ' + e.message, 'error', 8000);
    }
  }

  return teardown;
}

// Underline words the recogniser was unsure about or heard differently from the modelled phrase.
function userHtml(text, pron) {
  if (!pron || (!pron.low?.length && !pron.rep)) return escapeHtml(text);
  const flags = new Map();
  for (const w of pron.low || []) flags.set(w.word.toLowerCase(), `Unclear (${Math.round(w.p * 100)}% sure) — check the pronunciation`);
  for (const d of pron.rep?.diffs || []) {
    for (const w of (d.heard || '').split(' ').filter(Boolean)) flags.set(w.toLowerCase(), d.expected ? `Target: "${d.expected}"` : 'Extra word');
  }
  return text.split(/(\s+)/).map((tok) => {
    const key = tok.toLowerCase().replace(/[.,!?;:"'«»]/g, '');
    return flags.has(key) ? `<span class="unsure" title="${escapeHtml(flags.get(key))}">${escapeHtml(tok)}</span>` : escapeHtml(tok);
  }).join('') + (pron.rep?.diffs?.some((d) => d.expected && !d.heard) ? ` <span class="unsure" title="Missing: ${escapeHtml(pron.rep.diffs.filter((d) => !d.heard).map((d) => d.expected).join(', '))}">⋯</span>` : '');
}

function seg(options, value, onChange) {
  const el = h('div', { class: 'seg' });
  const buttons = options.map(([v, label, ic]) => h('button', { onclick: () => { el.set(v); onChange(v); } }, ic ? icon(ic, 14) : null, label));
  buttons.forEach((b, i) => b.dataset.v = options[i][0]);
  el.append(...buttons);
  el.set = (v) => buttons.forEach((b) => b.classList.toggle('active', b.dataset.v === v));
  el.set(value);
  return el;
}
