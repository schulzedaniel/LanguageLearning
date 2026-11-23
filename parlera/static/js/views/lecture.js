// A grammar lecture: the idea, how it works, steps with examples, table, contrast, mistakes, tips,
// an interactive quiz and follow-up questions. Target-language text is clickable to listen.
import { api, LANGS, teacher } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, spinner, fmtDate } from '../ui.js';
import { renderMarkdown } from '../markdown.js';
import { navigate } from '../nav.js';
import { say } from '../speech.js';

const md = (text) => { const d = h('div', { class: 'prose' }); d.innerHTML = renderMarkdown(text); return d; };

export default async function lecture(main, { id }) {
  mount(main, loading());
  let lec;
  try { lec = await api.get(`/api/lectures/${id}`); } catch (e) { mount(main, h('div', { class: 'page' }, h('div', { class: 'callout bad' }, e.message))); return; }
  const c = lec.content;
  const lang = lec.language;
  const L = LANGS[lang];
  const T = teacher(lang);
  const native = lang === 'en' ? null : 'English';
  const listen = (text) => h('button', { class: 'btn ghost sm icon-only', title: 'Listen', onclick: () => say(text, lang) }, icon('volume', 15));

  const section = (title, ...children) => h('section', { class: 'lecture-section' }, h('h2', {}, title), ...children);

  // --- quiz ---
  const quizScore = h('div', { class: 'small muted' });
  let answered = 0, correct = 0;
  const quizCards = c.quiz.map((q, qi) => {
    const fb = h('div');
    let done = false;
    const btns = q.options.map((o) => h('button', { class: 'choice-btn', onclick: () => {
      if (done) return; done = true;
      const ok = o === q.answer;
      answered += 1; if (ok) correct += 1;
      btns.forEach((b, i) => { b.disabled = true; if (q.options[i] === q.answer) b.classList.add('right'); else if (q.options[i] === o) b.classList.add('wrong'); });
      mount(fb, h('div', { class: `game-feedback ${ok ? 'good' : 'bad'}` }, h('b', {}, ok ? 'Correct! ' : 'Not quite. '), q.explanation || (ok ? '' : `Answer: ${q.answer}`)));
      quizScore.textContent = answered === c.quiz.length ? `Score: ${correct} / ${c.quiz.length}${correct === c.quiz.length ? ' 🎉' : ''}` : `${correct} / ${answered} so far`;
    } }, h('span', {}, o)));
    return h('div', { class: 'quiz-q' }, h('div', { class: 'quiz-n' }, `${qi + 1}`), h('div', { class: 'grow' }, md(q.question), h('div', { class: 'choice-list mt-xs' }, btns), fb));
  });

  // --- follow-ups ---
  const qaList = h('div', { class: 'col gap' }, (c.followups || []).map(qaItem));
  function qaItem(qa) {
    return h('div', { class: 'qa' }, h('div', { class: 'qa-q' }, icon('chat', 15), h('b', {}, qa.q)), md(qa.a));
  }
  const ask = h('textarea', { rows: 2, placeholder: `Ask ${T.name} anything about this topic, e.g. "Why is it different in questions?"` });
  const askBtn = h('button', { class: 'btn primary', onclick: async () => {
    const q = ask.value.trim(); if (!q) { ask.focus(); return; }
    askBtn.disabled = true; mount(askBtn, spinner(), ' Thinking…');
    try { const qa = await api.post(`/api/lectures/${lec.id}/ask`, { question: q }); qaList.append(qaItem(qa)); ask.value = ''; }
    catch (e) { toast(e.message, 'error', 7000); }
    askBtn.disabled = false; mount(askBtn, icon('send', 15), 'Ask');
  } }, icon('send', 15), 'Ask');

  const practise = async () => {
    const { startSession } = await import('./start.js');
    startSession({ mode: 'lesson', unit_id: lec.unit_id || undefined, focus: `Grammar: ${c.title}. ${c.speaking_task || ''}`.trim() });
  };

  const page = h('div', { class: 'page narrow lecture' },
    h('div', { class: 'row between mb' },
      h('a', { href: '#/practice/grammar', class: 'small' }, '← Grammar explained'),
      h('div', { class: 'row gap-sm' },
        h('button', { class: 'btn sm', onclick: practise }, icon('mic', 14), `Practise with ${T.name}`),
        h('button', { class: 'btn ghost sm icon-only', title: 'Delete this lecture', onclick: async () => {
          if (!(await confirmDialog(`Delete "${c.title}"?`, { title: 'Delete lecture', ok: 'Delete', danger: true }))) return;
          await api.del(`/api/lectures/${lec.id}`); navigate('practice/grammar');
        } }, icon('trash', 15)))),
    h('div', { class: 'lecture-head' },
      h('div', { class: 'row gap-sm' }, h('span', { class: 'badge accent' }, `${L.flag} ${L.name}`), lec.level ? h('span', { class: 'badge' }, lec.level) : null, h('span', { class: 'tiny faint' }, fmtDate(lec.created_at))),
      h('h1', {}, c.title),
      c.summary ? h('div', { class: 'lecture-summary' }, md(c.summary)) : null),
    c.mechanism ? section('How it works', md(c.mechanism)) : null,
    c.steps.length ? section('Step by step', ...c.steps.map((s, i) => h('div', { class: 'lecture-step' },
      h('div', { class: 'step-n' }, String(i + 1)),
      h('div', { class: 'grow' }, h('h3', {}, s.heading), md(s.explanation),
        s.examples.length ? h('div', { class: 'examples' }, s.examples.map((e) => h('div', { class: 'example' },
          listen(e.target), h('div', { class: 'grow' }, h('div', { class: 'ex-target' }, e.target.replace(/\*\*/g, '')),
            e.native ? h('div', { class: 'ex-native' }, e.native) : null, e.note ? h('div', { class: 'ex-note' }, e.note) : null)))) : null)))) : null,
    c.table?.columns?.length ? section(c.table.caption || 'Overview', h('div', { class: 'table-wrap' }, h('table', { class: 'lecture-table' },
      h('thead', {}, h('tr', {}, c.table.columns.map((col) => h('th', {}, col)))),
      h('tbody', {}, c.table.rows.map((r) => h('tr', {}, r.map((cell) => h('td', {}, cell)))))))) : null,
    c.contrast ? section(native ? `Compared with ${native}` : 'Don\'t confuse it with…', h('div', { class: 'callout' }, icon('info'), md(c.contrast))) : null,
    c.mistakes.length ? section('Typical mistakes', h('div', { class: 'col gap' }, c.mistakes.map((m) => h('div', { class: 'mistake' },
      h('div', {}, h('span', { class: 'wrong-text' }, m.wrong), ' → ', h('b', { class: 'right-text' }, m.right), listen(m.right)),
      m.why ? h('div', { class: 'small muted' }, m.why) : null)))) : null,
    c.tips.length ? section('Remember', h('ul', { class: 'tips' }, c.tips.map((t) => h('li', {}, md(t))))) : null,
    c.quiz.length ? section('Check yourself', h('div', { class: 'col gap' }, quizCards), h('div', { class: 'row between mt' }, quizScore,
      h('button', { class: 'btn ghost sm', onclick: () => lecture(main, { id }) }, icon('refresh', 14), 'Reset quiz'))) : null,
    section('Questions?', qaList, h('div', { class: 'col gap-sm mt' }, ask, h('div', { class: 'row end' }, askBtn))),
    h('div', { class: 'card accent-card mt' },
      h('div', { class: 'row between wrap gap' },
        h('div', {}, h('b', {}, 'Now use it'), h('div', { class: 'small muted' }, c.speaking_task || `Practise this topic in a short spoken lesson with ${T.name}.`)),
        h('button', { class: 'btn primary', onclick: practise }, icon('mic', 15), `Practise with ${T.name}`))));

  // clicking target-language words in the text plays them
  page.addEventListener('click', (e) => { const tl = e.target.closest('strong.tl'); if (tl) say(tl.dataset.tl || tl.textContent, lang); });
  mount(main, page);
}
