// Practice: short sessions without speaking.
//  - Quick games (local, no language model): flashcards, matching, multiple choice, fill the gap,
//    build the sentence, typing, gender sprint, fix my mistakes, and a mixed round.
//  - Grammar explained: structured lectures written by the (reasoning) model — see lecture.js.
import { api, state, LANGS, teacher } from '../api.js';
import { h, icon, mount, loading, toast, empty, fmtDate, confirmDialog, progressBar } from '../ui.js';
import { navigate } from '../nav.js';
import { say } from '../speech.js';

const SOURCES = [
  ['unit', 'Current unit', 'Words and phrases of your current unit and the ones just before it'],
  ['vocab', 'My words', 'Your vocabulary list (the words from your sessions and Anki)'],
  ['mix', 'Mix', 'Recent words plus your current unit'],
  ['misses', 'My misses', 'Items you got wrong recently, until you get them right twice in a row'],
];

const GENDER_LABEL = { sv: { en: 'en', ett: 'ett' }, fr: { m: 'le (masc.)', f: 'la (fém.)' } };

export const GAMES = [
  { id: 'mix', title: 'Quick mix', icon: 'sparkle', desc: 'A bit of everything: the best 5-minute round', min: 4 },
  { id: 'flashcards', title: 'Flashcards', icon: 'cards', desc: 'See it, recall it, flip it, rate yourself', min: 3 },
  { id: 'match', title: 'Match pairs', icon: 'target', desc: 'Connect words with their meanings', min: 4 },
  { id: 'choice', title: 'Multiple choice', icon: 'checkCircle', desc: 'Pick the right meaning or word', min: 4 },
  { id: 'cloze', title: 'Fill the gap', icon: 'edit', desc: 'Complete real sentences', min: 3 },
  { id: 'scramble', title: 'Build the sentence', icon: 'puzzle', desc: 'Put the words in the right order', min: 3 },
  { id: 'typing', title: 'Type it', icon: 'keyboard', desc: 'Write the word from its meaning', min: 3 },
  { id: 'gender', title: 'Gender sprint', icon: 'flame', desc: 'en or ett? le or la? Fast!', min: 4, langs: ['sv', 'fr'] },
  { id: 'fix', title: 'Fix my mistakes', icon: 'refresh', desc: 'Correct sentences you got wrong in sessions', min: 1, source: 'errors' },
];

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
const shuffle = (a) => { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };
const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
const clean = (s) => String(s || '').toLowerCase().replace(/[’`]/g, "'").replace(/[.,!?;:¿¡"«»“”()…]/g, ' ').replace(/\s+/g, ' ').trim();
const ARTICLES = { sv: ['en', 'ett', 'att'], fr: ['le', 'la', 'les', 'un', 'une', 'des', "l'"], en: ['a', 'an', 'the', 'to'] };
const noArticle = (s, lang) => {
  const c = clean(s);
  for (const a of ARTICLES[lang] || []) {
    if (a.endsWith("'") && c.startsWith(a)) return c.slice(a.length).trim();
    if (c.startsWith(a + ' ')) return c.slice(a.length + 1);
  }
  return c;
};

export function checkAnswer(input, answers, lang) {
  const a = clean(input);
  if (!a) return { ok: false };
  const cands = answers.filter(Boolean);
  if (cands.some((t) => clean(t) === a || noArticle(t, lang) === noArticle(a, lang))) return { ok: true };
  const hit = cands.find((t) => fold(clean(t)) === fold(a) || fold(noArticle(t, lang)) === fold(noArticle(a, lang)));
  if (hit) return { ok: true, note: `Watch the accents: ${hit}` };
  return { ok: false };
}

const scrambleSentence = (it) => {
  const s = (it.kind === 'phrase' ? it.term : it.example || '').trim();
  const n = s.split(/\s+/).length;
  return n >= 3 && n <= 10 && !/[…/]/.test(s) ? s : '';
};

function options(it, pool, field, k = 4) {
  const others = shuffle([...pool.items, ...pool.distractors].filter((o) => o[field] && clean(o[field]) !== clean(it[field])));
  const same = others.filter((o) => o.kind === it.kind);
  const picked = [];
  for (const o of [...same, ...others]) {
    if (picked.length >= k - 1) break;
    if (!picked.some((p) => clean(p) === clean(o[field]))) picked.push(o[field]);
  }
  return shuffle([it[field], ...picked]);
}

function questionsFor(game, pool, n, lang) {
  const items = pool.items;
  const make = {
    flash: (it) => ({ type: 'flash', it }),
    choice: (it, i) => ({ type: 'choice', it, dir: i % 2 ? 'm2t' : 't2m' }),
    typing: (it) => ({ type: 'typing', it }),
    cloze: (it) => ({ type: 'cloze', it }),
    scramble: (it) => ({ type: 'scramble', it, sentence: scrambleSentence(it) }),
    gender: (it) => ({ type: 'gender', it }),
    fix: (it) => ({ type: 'fix', it }),
  };
  const can = {
    choice: () => true,
    typing: (it) => it.kind !== 'fix' && it.bare.length <= 40,
    cloze: (it) => !!it.cloze,
    scramble: (it) => !!scrambleSentence(it),
    gender: (it) => !!it.gender && !!GENDER_LABEL[lang],
  };
  if (game === 'mix') {
    return items.slice(0, n).map((it, i) => {
      const types = ['cloze', 'scramble', 'gender', 'typing', 'choice'].filter((t) => can[t](it));
      const t = types.includes('cloze') && Math.random() < 0.45 ? 'cloze' : types[Math.floor(Math.random() * types.length)];
      return make[t](it, i);
    });
  }
  if (game === 'flashcards') return items.slice(0, n).map(make.flash);
  if (game === 'fix') return items.slice(0, n).map(make.fix);
  if (game === 'match') return items.slice(0, Math.max(5, Math.ceil(n / 5) * 5)).map((it) => ({ type: 'match', it }));
  return items.filter((it) => can[game](it)).slice(0, n).map((it, i) => make[game](it, i));
}

export function availability(pool, lang) {
  const out = {};
  for (const g of GAMES) {
    if (g.langs && !g.langs.includes(lang)) continue;
    out[g.id] = g.source === 'errors' ? (pool.counts?.errors || 0) : questionsFor(g.id, pool, 999, lang).length;
  }
  return out;
}

// ---------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------
export default async function practice(main, params = {}) {
  const lang = state.language;
  const L = LANGS[lang];
  const tab = params.tab === 'grammar' ? 'grammar' : 'games';
  mount(main, loading());
  const data = await api.get(`/api/practice/${lang}`);
  let source = localStorage.getItem('parlera.practice.source') || 'mix';
  if (!data.counts[source] && source !== 'mix' && source !== 'unit') source = 'mix';
  const n = data.round_length || 10;

  const st = data.stats;
  const statLine = h('div', { class: 'row wrap gap-sm' },
    h('span', { class: 'badge accent' }, icon('flame', 13), `${st.today} round${st.today === 1 ? '' : 's'} today`),
    st.week_total ? h('span', { class: 'badge' }, `This week: ${st.week_score}/${st.week_total} correct`) : null,
    st.week_minutes ? h('span', { class: 'badge' }, `${st.week_minutes} min`) : null);

  const tabs = h('div', { class: 'tabs' },
    h('button', { class: tab === 'games' ? 'active' : '', onclick: () => navigate('practice') }, icon('puzzle', 15), 'Quick games'),
    h('button', { class: tab === 'grammar' ? 'active' : '', onclick: () => navigate('practice/grammar') }, icon('lightbulb', 15), 'Grammar explained',
      data.lectures.length ? h('span', { class: 'count' }, data.lectures.length) : null));
  const body = h('div');

  mount(main, h('div', { class: 'page' },
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Practice'), h('div', { class: 'sub' }, `Short ${L.name} practice without speaking: games for words and phrases, and grammar explained step by step.`)),
      statLine),
    tabs, body));

  if (tab === 'grammar') return renderGrammar(body, data, lang);

  // ---- games tab ----
  const gameGrid = h('div', { class: 'grid c3 game-grid' });
  const sourceBar = h('div', { class: 'segmented', role: 'tablist' });
  let pool = null;

  async function loadPool() {
    mount(gameGrid, loading('Collecting your words…'));
    pool = await api.get(`/api/practice/${lang}/items?source=${source}&count=120`);
    renderSources();
    renderCards();
  }
  function renderSources() {
    mount(sourceBar, SOURCES.map(([id, label, title]) => {
      const count = id === 'mix' ? null : data.counts[id];
      const disabled = (id === 'vocab' || id === 'misses') && !count;
      return h('button', { class: source === id ? 'active' : '', disabled, title: disabled ? (id === 'misses' ? 'Nothing missed yet. Play a round first.' : 'No words yet. They are collected after sessions.') : title,
        onclick: () => { source = id; localStorage.setItem('parlera.practice.source', id); loadPool(); } },
      label, count != null ? h('span', { class: 'count' }, count) : null);
    }));
  }
  function renderCards() {
    const avail = availability(pool, lang);
    mount(gameGrid, GAMES.filter((g) => g.id in avail).map((g) => {
      const count = avail[g.id];
      const ok = count >= g.min;
      return h('button', { class: `game-card ${g.id === 'mix' ? 'featured' : ''}`, disabled: !ok,
        onclick: () => playGame(main, { game: g.id, source: g.source || source, n, lang, onExit: () => practice(main, params) }) },
      h('div', { class: 'gc-icon' }, icon(g.icon, 22)),
      h('div', { class: 'gc-title' }, g.title),
      h('div', { class: 'gc-desc' }, g.desc),
      h('div', { class: 'gc-meta' }, ok ? (g.id === 'fix' ? `${count} sentence${count === 1 ? '' : 's'}` : `${Math.min(count, g.id === 'match' ? Math.max(n, 10) : n)} questions · ~${Math.max(2, Math.round(Math.min(count, n) * 0.3))} min`)
        : g.id === 'fix' ? 'Collected after sessions' : g.id === 'gender' ? 'Needs nouns: try My words or Mix' : 'Not enough material in this source'));
    }));
  }

  mount(body,
    h('div', { class: 'row between wrap gap-sm mb' },
      h('div', { class: 'col', style: { gap: '6px' } }, h('div', { class: 'section-label', style: { margin: 0 } }, 'Practise with'), sourceBar),
      data.unit ? h('div', { class: 'small muted' }, `Current unit: ${data.unit.level} · ${data.unit.title}`) : null),
    gameGrid,
    h('div', { class: 'callout mt' }, icon('info'), h('div', {}, 'Games run on your computer without the language model, so they start instantly. ',
      'Missed items come back in ', h('b', {}, 'My misses'), ' until you get them right twice in a row. For spaced repetition across weeks, keep using your Anki deck.')));
  await loadPool();
}

// ---------------------------------------------------------------------------
// game player
// ---------------------------------------------------------------------------
export async function playGame(main, { game, source, n, lang, onExit }) {
  const L = LANGS[lang];
  mount(main, loading());
  const pool = await api.get(`/api/practice/${lang}/items?source=${source}&count=${Math.max(40, n * 4)}`);
  const qs = questionsFor(game, pool, n, lang);
  const meta = GAMES.find((g) => g.id === game);
  if (!qs.length) { toast('Not enough material for this game yet. Try another source.', 'info'); onExit(); return; }
  const results = [];
  const started = Date.now();
  let idx = 0;
  let keyHandler = null;
  const setKeys = (fn) => { keyHandler = fn; };
  const onKey = (e) => { if (keyHandler && !e.metaKey && !e.ctrlKey && !e.altKey) keyHandler(e); };
  document.addEventListener('keydown', onKey);
  const exit = () => { document.removeEventListener('keydown', onKey); onExit(); };

  const bar = h('div', { class: 'game-progress' });
  const stage = h('div', { class: 'game-stage' });
  mount(main, h('div', { class: 'page narrow' },
    h('div', { class: 'row between mb' },
      h('div', { class: 'row gap-sm' }, icon(meta.icon, 20), h('b', {}, meta.title), h('span', { class: 'badge' }, SOURCES.find((s) => s[0] === source)?.[1] || 'Your mistakes')),
      h('button', { class: 'btn ghost sm', onclick: async () => { if (!results.length || await confirmDialog('Stop this round? Answers so far are saved.', { title: 'Stop round', ok: 'Stop' })) { if (results.length) await save(); exit(); } } }, icon('x', 15), 'Stop')),
    bar, stage));

  const record = (it, correct) => results.push({ term: it.term, meaning: it.meaning, vocab_id: it.vocab_id, correct: !!correct, it });
  const save = () => api.post(`/api/practice/${lang}/results`, { game, source, seconds: Math.round((Date.now() - started) / 1000),
    results: results.map(({ it, ...r }) => r) }).catch((e) => { toast(e.message, 'error'); return null; });

  const listenBtn = (text) => h('button', { class: 'btn ghost sm icon-only', title: 'Listen', onclick: (e) => { e.stopPropagation(); say(text, lang); } }, icon('volume', 16));

  function updateBar() {
    const total = game === 'match' ? qs.length : qs.length;
    mount(bar, progressBar(Math.min(1, idx / total)), h('div', { class: 'tiny faint mt-xs' }, `${Math.min(idx + 1, total)} / ${total}`));
  }

  // feedback panel shown after an answer; Enter continues
  function feedback(ok, it, { note = '', answer = '' } = {}) {
    const next = h('button', { class: 'btn primary', onclick: () => advance() }, idx + 1 >= qs.length ? 'See results' : 'Next', icon('arrowRight', 15));
    setKeys((e) => { if (e.key === 'Enter') { e.preventDefault(); advance(); } });
    setTimeout(() => next.focus(), 30);
    return h('div', { class: `game-feedback ${ok ? 'good' : 'bad'}` },
      h('div', { class: 'row gap-sm' }, icon(ok ? 'checkCircle' : 'alert', 18), h('b', {}, ok ? pick(['Correct!', 'Nice!', 'Exactly!', 'Perfect!']) : 'Not quite.')),
      !ok || note ? h('div', { class: 'mt-xs' }, note ? h('div', { class: 'small' }, note) : null,
        !ok ? h('div', { class: 'row gap-sm' }, h('span', { class: 'small muted' }, 'Answer:'), h('b', { class: 'tl-text' }, answer || it.term), listenBtn(answer || it.term)) : null) : null,
      it.meaning && it.kind !== 'fix' ? h('div', { class: 'small muted mt-xs' }, `${it.term} = ${it.meaning}`) : null,
      it.kind === 'fix' && it.meaning ? h('div', { class: 'small muted mt-xs' }, it.meaning) : null,
      h('div', { class: 'row end mt' }, next));
  }
  const pick = (a) => a[Math.floor(Math.random() * a.length)];

  function advance() {
    idx += 1;
    if (idx >= qs.length) finish();
    else show();
  }

  function show() {
    updateBar();
    setKeys(null);
    const q = qs[idx];
    const it = q.it;
    const R = renderers[q.type];
    R(q, it);
  }

  const renderers = {
    flash(q, it) {
      const back = h('div', { class: 'flash-back hidden' }, h('div', { class: 'flash-meaning' }, it.meaning),
        it.example ? h('div', { class: 'small muted mt-xs' }, it.example) : null);
      const rate = h('div', { class: 'row center gap mt hidden' },
        h('button', { class: 'btn', onclick: () => { record(it, false); advance(); } }, icon('refresh', 15), 'Again', h('kbd', {}, '1')),
        h('button', { class: 'btn primary', onclick: () => { record(it, true); advance(); } }, icon('check', 15), 'Got it', h('kbd', {}, '2')));
      const flip = h('button', { class: 'btn primary', onclick: () => reveal() }, 'Show meaning', h('kbd', {}, 'Space'));
      const reveal = () => { back.classList.remove('hidden'); rate.classList.remove('hidden'); flip.remove();
        setKeys((e) => { if (e.key === '1') { record(it, false); advance(); } if (e.key === '2' || e.key === 'Enter') { record(it, true); advance(); } }); };
      setKeys((e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); reveal(); } });
      mount(stage, h('div', { class: 'card game-card-big' },
        h('div', { class: 'tiny faint' }, 'Do you know what this means? Say it in your head, then flip.'),
        h('div', { class: 'row center gap-sm mt' }, h('div', { class: 'flash-term' }, it.term), listenBtn(it.term)),
        back, h('div', { class: 'row center mt' }, flip), rate));
      say(it.term, lang);
    },

    choice(q, it) {
      const t2m = q.dir === 't2m';
      const opts = options(it, pool, t2m ? 'meaning' : 'term');
      const right = t2m ? it.meaning : it.term;
      const fb = h('div');
      let done = false;
      const buttons = opts.map((o, i) => h('button', { class: 'choice-btn', onclick: () => answer(o, i) }, h('kbd', {}, String(i + 1)), h('span', {}, o)));
      const answer = (o) => {
        if (done) return; done = true;
        const ok = clean(o) === clean(right);
        buttons.forEach((b, i) => { b.disabled = true; if (clean(opts[i]) === clean(right)) b.classList.add('right'); else if (opts[i] === o) b.classList.add('wrong'); });
        record(it, ok);
        mount(fb, feedback(ok, it, { answer: it.term }));
      };
      setKeys((e) => { const k = Number(e.key); if (k >= 1 && k <= opts.length) answer(opts[k - 1]); });
      mount(stage, h('div', { class: 'card game-card-big' },
        h('div', { class: 'tiny faint' }, t2m ? 'What does this mean?' : `How do you say this in ${L.name}?`),
        h('div', { class: 'row center gap-sm mt' }, h('div', { class: t2m ? 'flash-term' : 'flash-meaning' }, t2m ? it.term : it.meaning), t2m ? listenBtn(it.term) : null),
        h('div', { class: 'choice-list mt' }, buttons), fb));
      if (t2m) say(it.term, lang);
    },

    typing(q, it) { typed(it, `Type the ${L.name} for:`, h('div', { class: 'flash-meaning' }, it.meaning), [it.term, it.bare], it.term); },

    cloze(q, it) {
      const c = it.cloze;
      const hint = h('button', { class: 'btn ghost sm hint-btn', onclick: (e) => { input.placeholder = `${c.answer[0]}${'·'.repeat(Math.max(0, c.answer.length - 1))}`; e.currentTarget.remove(); input.focus(); } }, icon('lightbulb', 14), 'First letter');
      const input = h('input', { type: 'text', class: 'gap-input', autocomplete: 'off', autocapitalize: 'off', spellcheck: false, style: { width: `${Math.max(5, c.answer.length + 2)}ch` } });
      typed(it, 'Fill the gap:', h('div', {},
        h('div', { class: 'cloze-sentence' }, c.before, input, c.after),
        c.hint ? h('div', { class: 'small muted mt-xs' }, c.hint) : null, h('div', { class: 'row center mt-xs' }, hint)),
      [c.answer], c.answer, input, `${c.before}${c.answer}${c.after}`);
    },

    fix(q, it) {
      const input = h('textarea', { rows: 2, class: 'fix-input', spellcheck: false }, it.wrong);
      typed(it, 'This sentence has a mistake. Correct it:', h('div', {}, h('div', { class: 'wrong-sentence' }, it.wrong), it.pattern ? h('div', { class: 'tiny faint mt-xs' }, `Hint: ${it.pattern}`) : null), [it.term], it.term, input);
    },

    gender(q, it) {
      const opts = Object.entries(GENDER_LABEL[lang]);
      const fb = h('div');
      let done = false;
      const buttons = opts.map(([g, label], i) => h('button', { class: 'choice-btn center', onclick: () => answer(g) }, h('kbd', {}, String(i + 1)), h('span', {}, label)));
      const answer = (g) => {
        if (done) return; done = true;
        const ok = g === it.gender;
        buttons.forEach((b, i) => { b.disabled = true; if (opts[i][0] === it.gender) b.classList.add('right'); else if (opts[i][0] === g) b.classList.add('wrong'); });
        record(it, ok);
        mount(fb, feedback(ok, it, { answer: it.term }));
      };
      setKeys((e) => { const k = Number(e.key); if (k >= 1 && k <= opts.length) answer(opts[k - 1][0]); });
      mount(stage, h('div', { class: 'card game-card-big' },
        h('div', { class: 'tiny faint' }, lang === 'sv' ? 'en or ett?' : 'Masculine or feminine?'),
        h('div', { class: 'flash-term mt' }, it.bare), h('div', { class: 'small muted' }, it.meaning),
        h('div', { class: 'choice-list two mt' }, buttons), fb));
    },

    scramble(q, it) {
      const words = q.sentence.split(/\s+/);
      let order = shuffle(words.map((w, i) => i));
      for (let t = 0; t < 5 && order.every((v, i) => v === i); t++) order = shuffle(order);
      const chosen = [];
      const built = h('div', { class: 'scramble-built' });
      const bank = h('div', { class: 'scramble-bank' });
      const fb = h('div');
      let done = false;
      const render = () => {
        mount(built, chosen.length ? chosen.map((wi, k) => h('button', { class: 'word-chip on', disabled: done, onclick: () => { chosen.splice(k, 1); render(); } }, words[wi]))
          : h('span', { class: 'faint small' }, 'Tap the words in the right order'));
        mount(bank, order.map((wi) => h('button', { class: 'word-chip', disabled: done || chosen.includes(wi), onclick: () => { chosen.push(wi); render(); if (chosen.length === words.length) check(); } }, words[wi])));
      };
      const check = () => {
        done = true;
        const attempt = chosen.map((i) => words[i]).join(' ');
        const ok = clean(attempt) === clean(q.sentence);
        record(it, ok);
        render();
        mount(fb, feedback(ok, { ...it, meaning: it.kind === 'phrase' ? it.meaning : it.example_translation || it.meaning }, { answer: q.sentence }));
        if (ok) say(q.sentence, lang);
      };
      setKeys((e) => { if (e.key === 'Backspace' && chosen.length && !done) { chosen.pop(); render(); } });
      render();
      const hint = it.kind === 'phrase' ? it.meaning : (it.example_translation || '');
      mount(stage, h('div', { class: 'card game-card-big' },
        h('div', { class: 'tiny faint' }, 'Build the sentence'), hint ? h('div', { class: 'flash-meaning small-ish mt-xs' }, hint) : null,
        built, bank, fb));
    },

    match() { matchBoards(); },
  };

  // typed answers (typing, cloze, fix)
  function typed(it, label, prompt, answers, display, input = null, speakAfter = null) {
    input ||= h('input', { type: 'text', class: 'answer-input', autocomplete: 'off', autocapitalize: 'off', spellcheck: false, placeholder: 'Type your answer' });
    const fb = h('div');
    let done = false;
    const submit = () => {
      if (done) return;
      if (!input.value.trim()) { input.focus(); return; }
      done = true;
      const res = checkAnswer(input.value, answers, lang);
      input.disabled = true;
      input.classList.add(res.ok ? 'right' : 'wrong');
      record(it, res.ok);
      submitBtn.remove(); skip.remove(); stage.querySelector('.hint-btn')?.remove();
      mount(fb, feedback(res.ok, it, { note: res.note, answer: display }));
      say(speakAfter || display, lang);
    };
    const submitBtn = h('button', { class: 'btn primary', onclick: submit }, 'Check');
    const skip = h('button', { class: 'btn ghost', onclick: () => { input.value = input.value || ' '; if (!done) { done = true; input.disabled = true; record(it, false); submitBtn.remove(); skip.remove(); stage.querySelector('.hint-btn')?.remove(); mount(fb, feedback(false, it, { answer: display })); } } }, "I don't know");
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); if (!done) submit(); else advance(); } });
    const isInline = input.classList.contains('gap-input');
    mount(stage, h('div', { class: 'card game-card-big' },
      h('div', { class: 'tiny faint' }, label), h('div', { class: 'mt' }, prompt),
      isInline ? null : h('div', { class: 'mt' }, input),
      h('div', { class: 'row center gap-sm mt' }, skip, submitBtn), fb));
    setTimeout(() => input.focus(), 30);
    setKeys((e) => { if (done && e.key === 'Enter') { e.preventDefault(); advance(); } });
  }

  // matching: boards of 5 pairs
  function matchBoards() {
    const all = qs.map((q) => q.it);
    const boards = [];
    for (let i = 0; i < all.length; i += 5) boards.push(all.slice(i, i + 5));
    let b = 0;
    const board = () => {
      const items = boards[b];
      if (!items || items.length < 2) { idx = qs.length; finish(); return; }
      const missed = new Set();
      let sel = null;
      let solved = 0;
      const left = shuffle(items).map((it) => h('button', { class: 'match-btn', onclick: (e) => choose(e.currentTarget, it, 'l') }, it.term));
      const right = shuffle(items).map((it) => h('button', { class: 'match-btn', onclick: (e) => choose(e.currentTarget, it, 'r') }, it.meaning));
      const choose = (el, it, side) => {
        if (el.classList.contains('done')) return;
        if (!sel || sel.side === side) { sel?.el.classList.remove('sel'); sel = { el, it, side }; el.classList.add('sel'); if (side === 'l') say(it.term, lang); return; }
        if (sel.it === it) {
          [sel.el, el].forEach((x) => { x.classList.remove('sel'); x.classList.add('done'); x.disabled = true; });
          record(it, !missed.has(it.key));
          solved += 1; idx += 1; updateBar();
          sel = null;
          if (solved === items.length) setTimeout(() => { b += 1; if (b < boards.length) board(); else finish(); }, 450);
        } else {
          missed.add(sel.it.key); missed.add(it.key);
          [sel.el, el].forEach((x) => { x.classList.add('shake'); setTimeout(() => x.classList.remove('shake', 'sel'), 450); });
          sel = null;
        }
      };
      mount(stage, h('div', { class: 'card game-card-big' },
        h('div', { class: 'tiny faint' }, `Match the pairs${boards.length > 1 ? ` · board ${b + 1} of ${boards.length}` : ''}`),
        h('div', { class: 'match-grid mt' }, h('div', { class: 'col' }, left), h('div', { class: 'col' }, right))));
    };
    idx = 0; updateBar(); board();
  }

  async function finish() {
    setKeys(null);
    mount(bar, progressBar(1));
    const saved = await save();
    const score = results.filter((r) => r.correct).length;
    const missed = results.filter((r) => !r.correct);
    const pct = results.length ? score / results.length : 0;
    const secs = Math.round((Date.now() - started) / 1000);
    const addBtn = (r) => (r.it.vocab_id || r.it.kind === 'fix') ? null : h('button', { class: 'btn ghost sm', title: 'Add to your vocabulary (and Anki)', onclick: async (e) => {
      const btn = e.currentTarget; btn.disabled = true;
      try { await api.post('/api/vocab', { language: lang, lemma: r.it.bare || r.it.term, translation: r.it.meaning, gender: r.it.gender || '', example: r.it.example || '', example_translation: r.it.example_translation || '', status: 'learning' });
        mount(btn, icon('check', 14), 'Added'); } catch (err) { toast(err.message, 'error'); btn.disabled = false; }
    } }, icon('plus', 14), 'My words');
    mount(stage, h('div', { class: 'card game-card-big' },
      h('div', { class: 'result-score' }, `${score} / ${results.length}`),
      h('div', { class: 'muted' }, pct === 1 ? 'Flawless! 🎉' : pct >= 0.8 ? 'Great round!' : pct >= 0.5 ? 'Good work. The misses will come back until they stick.' : 'Tough round. That\'s how learning feels. Try the misses again in a moment.'),
      h('div', { class: 'tiny faint mt-xs' }, `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')} min${saved?.stats ? ` · ${saved.stats.today} round${saved.stats.today === 1 ? '' : 's'} today` : ''}`),
      missed.length ? h('div', { class: 'missed-list mt' }, h('div', { class: 'section-label' }, 'To practise'),
        missed.map((r) => h('div', { class: 'missed-row' }, listenBtn(r.it.term), h('b', {}, r.it.term), h('span', { class: 'muted small grow' }, r.it.kind === 'fix' ? `not: ${r.it.wrong}` : r.it.meaning), addBtn(r)))) : null,
      h('div', { class: 'row center wrap gap-sm mt' },
        h('button', { class: 'btn', onclick: exit }, icon('arrowLeft', 15), 'All games'),
        missed.length && source !== 'errors' ? h('button', { class: 'btn', onclick: () => { document.removeEventListener('keydown', onKey); playGame(main, { game: game === 'match' ? 'choice' : game, source: 'misses', n, lang, onExit }); } }, icon('refresh', 15), 'Practise my misses') : null,
        h('button', { class: 'btn primary', onclick: () => { document.removeEventListener('keydown', onKey); playGame(main, { game, source, n, lang, onExit }); } }, icon('play', 15), 'Play again'))));
  }

  show();
}

// ---------------------------------------------------------------------------
// Grammar tab
// ---------------------------------------------------------------------------
function renderGrammar(body, data, lang) {
  const T = teacher(lang);
  const existing = (topic) => data.lectures.find((l) => l.topic.toLowerCase() === topic.toLowerCase());
  const input = h('input', { type: 'text', placeholder: lang === 'sv' ? 'e.g. word order in subordinate clauses, or "when do I use ett?"' : lang === 'fr' ? 'e.g. passé composé vs. imparfait, or "when do I use en and y?"' : 'e.g. mixed conditionals, or "inversion after negative adverbials"' });
  const go = () => { const t = input.value.trim(); if (t) explainGrammar(lang, t); else input.focus(); };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });

  const topicRow = (t) => {
    const done = existing(t.topic);
    return h('button', { class: `topic-row ${t.current ? 'current' : ''}`, onclick: () => (done ? navigate(`lecture/${done.id}`) : explainGrammar(lang, t.topic, t.unit_id)) },
      h('div', { class: 'grow' }, h('div', {}, t.topic), h('div', { class: 'tiny faint' }, t.unit_title)),
      t.current ? h('span', { class: 'badge accent' }, 'current unit') : null,
      done ? h('span', { class: 'badge good' }, icon('check', 12), 'read') : h('span', { class: 'small muted' }, 'Explain ›'));
  };

  mount(body,
    h('div', { class: 'grid c2 align-start' },
      h('div', { class: 'col gap-lg' },
        h('div', { class: 'card' },
          h('h3', {}, 'Ask about any grammar topic'),
          h('div', { class: 'small muted mt-xs' }, `${T.name} writes a short lecture: the idea, how it works and why, examples, a comparison with English, typical mistakes and a quiz.`),
          h('div', { class: 'row gap-sm mt' }, h('div', { class: 'grow' }, input), h('button', { class: 'btn primary', onclick: go }, icon('lightbulb', 15), 'Explain')),
          h('div', { class: 'tiny faint mt-xs' }, 'Uses the analysis model (with thinking if enabled), so it takes a minute or two. Lectures are saved for re-reading.')),
        h('div', { class: 'card' },
          h('div', { class: 'card-head' }, h('h3', {}, 'Saved lectures'), h('span', { class: 'small muted' }, data.lectures.length || '')),
          data.lectures.length ? h('div', { class: 'col mt' }, data.lectures.map((l) => h('div', { class: 'lecture-row' },
            h('a', { href: `#/lecture/${l.id}`, class: 'grow' }, h('div', {}, h('b', {}, l.title)), h('div', { class: 'tiny faint' }, `${l.level || ''} · ${fmtDate(l.created_at)}`)),
            h('button', { class: 'btn ghost sm icon-only', title: 'Delete', onclick: async () => {
              if (!(await confirmDialog(`Delete the lecture "${l.title}"?`, { title: 'Delete lecture', ok: 'Delete', danger: true }))) return;
              await api.del(`/api/lectures/${l.id}`); navigate('practice/grammar'); window.dispatchEvent(new HashChangeEvent('hashchange'));
            } }, icon('trash', 15)))))
            : empty('lightbulb', 'No lectures yet. Pick a topic from your curriculum or ask about anything.'))),
      h('div', { class: 'card' },
        h('h3', {}, 'From your curriculum'),
        h('div', { class: 'small muted mt-xs' }, 'The grammar of your units so far and the next level. Topics you have read are ticked.'),
        data.topics.length ? data.topics.slice().reverse().map((g) => h('div', { class: 'mt' },
          h('div', { class: 'section-label' }, g.level),
          h('div', { class: 'col', style: { gap: '4px' } }, g.topics.map(topicRow))))
          : empty('book', 'No grammar topics in this curriculum.'))));
}

export async function explainGrammar(lang, topic, unitId = null, { force = false } = {}) {
  const T = teacher(lang);
  if (!force) {  // already written? open it instead of writing it again
    const saved = await api.get(`/api/lectures?language=${lang}`).catch(() => []);
    const hit = saved.find((l) => l.topic.trim().toLowerCase() === topic.trim().toLowerCase());
    if (hit) { navigate(`lecture/${hit.id}`); return; }
  }
  const overlay = h('div', { class: 'overlay' }, h('div', { class: 'overlay-box' },
    h('div', { class: 'spinner lg' }),
    h('h2', {}, `${T.name} is preparing your lecture`),
    h('div', { class: 'muted' }, `“${topic}”`),
    h('div', { class: 'small faint mt' }, 'Thinking it through: explanation, examples, typical mistakes and a quiz. This can take a minute or two with a reasoning model.')));
  document.body.append(overlay);
  try {
    const lec = await api.post('/api/lectures', { language: lang, topic, unit_id: unitId });
    navigate(`lecture/${lec.id}`);
  } catch (e) {
    toast(`Couldn't write the lecture: ${e.message}`, 'error', 8000);
  } finally {
    overlay.remove();
  }
}
