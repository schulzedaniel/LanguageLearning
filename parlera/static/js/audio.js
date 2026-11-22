// Audio: microphone capture with voice-activity detection, WAV encoding, and a playback queue.

export function b64FromBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function bufferFromB64(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function downsample(input, from, to) {
  if (from === to) return input;
  const ratio = from / to;
  const n = Math.floor(input.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

function concat(chunks) {
  const len = chunks.reduce((a, c) => a + c.length, 0);
  const out = new Float32Array(len);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

// ---------------------------------------------------------------------------
// Recorder with simple adaptive energy VAD
// ---------------------------------------------------------------------------
export class Recorder {
  constructor({ silenceMs = 1400, onLevel, onSpeechStart, onUtterance, onState } = {}) {
    this.silenceMs = silenceMs;
    this.onLevel = onLevel || (() => {});
    this.onSpeechStart = onSpeechStart || (() => {});
    this.onUtterance = onUtterance || (() => {});
    this.onState = onState || (() => {});
    this.mode = 'handsfree';
    this.paused = false;
    this.bargeIn = false;
    this.state = 'off';
    this.noise = 0.006;
    this.preroll = [];
    this.chunks = [];
  }

  async start() {
    if (this.ctx) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.rate = this.ctx.sampleRate;
    const src = this.ctx.createMediaStreamSource(this.stream);
    const handle = (frame) => this._frame(frame);
    if (this.ctx.audioWorklet) {
      await this.ctx.audioWorklet.addModule('/static/js/recorder-worklet.js');
      this.node = new AudioWorkletNode(this.ctx, 'recorder-processor');
      this.node.port.onmessage = (e) => handle(e.data);
      src.connect(this.node);
    } else {
      this.node = this.ctx.createScriptProcessor(2048, 1, 1);
      this.node.onaudioprocess = (e) => handle(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(this.node);
      this.node.connect(this.ctx.destination);
    }
    this._reset();
    this._setState(this.mode === 'handsfree' ? 'listening' : 'ready');
  }

  stop() {
    try { this.node?.disconnect(); } catch { /* ignore */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.ctx = null; this.node = null; this.stream = null;
    this._setState('off');
  }

  setMode(mode) {
    this.mode = mode;
    this._reset();
    if (this.ctx) this._setState(mode === 'handsfree' ? 'listening' : 'ready');
  }

  setPaused(p) {
    this.paused = p;
    if (p && this.state === 'speaking' && this.mode === 'handsfree') this._reset();
    if (this.ctx && this.mode === 'handsfree' && this.state !== 'speaking') this._setState(p ? 'paused' : 'listening');
  }

  pttStart() {
    if (!this.ctx) return;
    this.ctx.resume();
    this.chunks = [...this.preroll];
    this.recording = true;
    this.speechStart = performance.now();
    this._setState('speaking');
    this.onSpeechStart();
  }

  pttStop() {
    if (!this.recording) return;
    this.recording = false;
    this._emit();
    this._setState('ready');
  }

  _reset() {
    this.chunks = []; this.recording = false; this.loud = 0; this.quiet = 0;
  }

  _setState(s) { if (this.state !== s) { this.state = s; this.onState(s); } }

  _frame(frame) {
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    const rms = Math.sqrt(sum / frame.length);
    const ms = (frame.length / this.rate) * 1000;
    this.onLevel(rms);

    // keep ~300 ms of pre-roll so the first syllable isn't cut off
    this.preroll.push(frame);
    let pre = this.preroll.reduce((a, c) => a + c.length, 0);
    while (pre > this.rate * 0.3) { pre -= this.preroll.shift().length; }

    if (this.mode === 'ptt') {
      if (this.recording) {
        this.chunks.push(frame);
        if (performance.now() - this.speechStart > 90000) this.pttStop();
      }
      return;
    }
    if (this.mode !== 'handsfree') return;

    const threshold = Math.max(0.012, this.noise * 3) * (this.paused && this.bargeIn ? 2.2 : 1);
    if (this.paused && !this.bargeIn) { this._updateNoise(rms); return; }

    if (!this.recording) {
      if (rms > threshold) {
        this.loud += ms;
        if (this.loud >= 90) {
          this.recording = true;
          this.chunks = [...this.preroll];
          this.speechStart = performance.now();
          this.quiet = 0;
          this._setState('speaking');
          this.onSpeechStart();
        }
      } else {
        this.loud = 0;
        this._updateNoise(rms);
      }
      return;
    }
    this.chunks.push(frame);
    if (rms < threshold * 0.8) this.quiet += ms; else this.quiet = 0;
    const dur = performance.now() - this.speechStart;
    if (this.quiet >= this.silenceMs || dur > 60000) {
      this.recording = false;
      this.loud = 0;
      if (dur - this.quiet >= 350) this._emit();
      this.chunks = [];
      this._setState(this.paused ? 'paused' : 'listening');
    }
  }

  _updateNoise(rms) { this.noise = 0.95 * this.noise + 0.05 * Math.min(rms, 0.05); }

  _emit() {
    const audio = downsample(concat(this.chunks), this.rate, 16000);
    this.chunks = [];
    if (audio.length < 16000 * 0.3) return;
    this.onUtterance(encodeWav(audio, 16000));
  }
}

// ---------------------------------------------------------------------------
// Playback queue: WAV buffers from the server or browser speechSynthesis segments
// ---------------------------------------------------------------------------
const BROWSER_LANG = { sv: 'sv-SE', fr: 'fr-FR', en: 'en-US' };

export class Player {
  constructor({ onStart, onIdle, voices = {} } = {}) {
    this.queue = [];
    this.playing = false;
    this.streamOpen = false;
    this.onStart = onStart || (() => {});
    this.onIdle = onIdle || (() => {});
    this.voicePrefs = voices;
    this.gen = 0;
  }

  ensureContext() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  openStream() { this.streamOpen = true; }
  endStream() { this.streamOpen = false; if (!this.playing && !this.queue.length) this.onIdle(); }

  enqueueWav(arrayBuffer, meta = {}) { this.queue.push({ kind: 'wav', data: arrayBuffer, meta }); this._pump(); }
  enqueueSpeech(segments, rates = {}, meta = {}) { this.queue.push({ kind: 'speech', segments, rates, meta }); this._pump(); }

  get busy() { return this.playing || this.queue.length > 0 || this.streamOpen; }

  stop() {
    this.gen++;
    this.queue = [];
    this.streamOpen = false;
    try { this.source?.stop(); } catch { /* ignore */ }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    const was = this.playing;
    this.playing = false;
    if (was) this.onIdle();
  }

  async _pump() {
    if (this.playing) return;
    const item = this.queue.shift();
    if (!item) { if (!this.streamOpen) this.onIdle(); return; }
    this.playing = true;
    const gen = this.gen;
    this.onStart(item.meta);
    try {
      if (item.kind === 'wav') await this._playWav(item.data);
      else await this._speak(item.segments, item.rates);
    } catch (e) { console.warn('playback failed', e); }
    if (gen !== this.gen) return;
    this.playing = false;
    this._pump();
  }

  async _playWav(data) {
    const ctx = this.ensureContext();
    const buf = await ctx.decodeAudioData(data.slice(0));
    await new Promise((resolve) => {
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.onended = resolve;
      this.source = src;
      src.start();
    });
  }

  _voiceFor(lang) {
    const all = speechSynthesis.getVoices();
    const pref = this.voicePrefs[lang];
    if (pref) { const v = all.find((x) => x.name === pref); if (v) return v; }
    const code = BROWSER_LANG[lang] || lang;
    const cands = all.filter((v) => v.lang.replace('_', '-').toLowerCase().startsWith(code.slice(0, 2).toLowerCase()));
    return cands.find((v) => /premium|enhanced|natural|neural/i.test(v.name) && v.lang.replace('_', '-') === code)
      || cands.find((v) => v.lang.replace('_', '-') === code) || cands[0] || null;
  }

  async _speak(segments, rates) {
    if (!('speechSynthesis' in window)) return;
    for (const seg of segments) {
      await new Promise((resolve) => {
        const u = new SpeechSynthesisUtterance(seg.text);
        u.lang = BROWSER_LANG[seg.lang] || seg.lang;
        const v = this._voiceFor(seg.lang);
        if (v) u.voice = v;
        u.rate = rates?.[seg.lang] ?? 1;
        // safety net: some engines never fire onend (e.g. voice missing)
        const guard = setTimeout(resolve, 4000 + seg.text.length * 150 / (u.rate || 1));
        u.onend = () => { clearTimeout(guard); resolve(); };
        u.onerror = () => { clearTimeout(guard); resolve(); };
        speechSynthesis.speak(u);
      });
    }
  }
}
