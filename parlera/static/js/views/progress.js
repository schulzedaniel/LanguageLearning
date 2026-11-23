// How far a unit is, in plain words: a unit is complete when you have enough *reviewed* sessions on it
// and your mastery (the teacher's estimate after each End & review) reaches the target.
import { h, icon } from '../ui.js';

// st: { sessions_reviewed, min_sessions, mastery, threshold, status }
export function masteryBar(mastery, threshold, cls = '') {
  const pct = Math.round((mastery || 0) * 100);
  return h('div', { class: `goal-bar ${cls}`, title: `Mastery ${pct}% · ${Math.round(threshold * 100)}% needed` },
    h('div', { class: `fill ${mastery >= threshold ? 'ok' : ''}`, style: { width: `${Math.min(100, pct)}%` } }),
    h('div', { class: 'target', style: { left: `${Math.round(threshold * 100)}%` } }));
}

export function unitChecklist(st, { compact = false } = {}) {
  const sessionsOk = st.sessions_reviewed >= st.min_sessions;
  const masteryOk = st.mastery >= st.threshold;
  const pct = Math.round((st.mastery || 0) * 100);
  const need = Math.round(st.threshold * 100);
  if (st.status === 'completed') {
    return h('div', { class: 'unit-check done' }, icon('checkCircle', 15), compact ? 'Completed' : `Unit completed · mastery ${pct}%`);
  }
  if (compact) {
    return h('div', { class: 'unit-check compact' },
      h('span', { class: sessionsOk ? 'ok' : '' }, `${Math.min(st.sessions_reviewed, st.min_sessions)}/${st.min_sessions} sessions`),
      masteryBar(st.mastery, st.threshold, 'thin'),
      h('span', { class: masteryOk ? 'ok' : '' }, `${pct}%`));
  }
  return h('div', { class: 'unit-check' },
    h('div', { class: 'uc-row' }, icon(sessionsOk ? 'checkCircle' : 'circle', 15, sessionsOk ? 'ok' : ''),
      h('span', { class: 'uc-label' }, 'Reviewed sessions'),
      h('b', {}, `${st.sessions_reviewed} of ${st.min_sessions}`), sessionsOk ? null : h('span', { class: 'faint' }, ` · ${st.min_sessions - st.sessions_reviewed} more needed`)),
    h('div', { class: 'uc-row' }, icon(masteryOk ? 'checkCircle' : 'circle', 15, masteryOk ? 'ok' : ''),
      h('span', { class: 'uc-label' }, 'Mastery'),
      masteryBar(st.mastery, st.threshold),
      h('b', {}, `${pct}%`), h('span', { class: 'faint' }, ` / ${need}% needed`)),
    h('div', { class: 'tiny faint' }, 'Only sessions you finish with End & review count. Mastery is your teacher\'s estimate of how well you handle this unit\'s goals, averaged over those sessions.'));
}

// a unit's status from the curriculum endpoint's data
export function statusFromProgress(unit, progress, threshold) {
  const p = progress || {};
  return { sessions_reviewed: p.sessions || 0, min_sessions: unit.min_sessions || 1, mastery: p.mastery || 0, threshold, status: p.status || 'active' };
}
