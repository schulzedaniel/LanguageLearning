// Sessions: grouped by curriculum level → unit (or by date), with a clear status for every session:
// Reviewed, Unfinished (continue here), Older unfinished, or Continued after review.
import { renderMarkdown } from '../markdown.js';
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, fmtDate, fmtDuration, empty, promptDialog } from '../ui.js';
import { navigate } from '../nav.js';
import { openStartDialog } from './start.js';
import { unitChecklist, statusFromProgress } from './progress.js';

const MODE_ICON = { lesson: 'school', conversation: 'chat', roleplay: 'theater', review: 'refresh', exam: 'award', writing: 'pen', placement: 'compass', free: 'sparkle', pronunciation: 'wave', workshop: 'target', break: 'coffee' };
const MODE_TITLE = { lesson: 'Guided lesson', conversation: 'Conversation', roleplay: 'Role-play', review: 'Review & quiz', exam: 'Exam practice', writing: 'Writing', placement: 'Placement check', free: 'Free talk', pronunciation: 'Pronunciation', workshop: 'Mistake workshop', break: 'Chat break' };

export default async function history(main, params = {}) {
  const lang = state.language;
  let view = params.tab === 'archive' ? 'archive' : 'recent';
  let grouping = 'unit';
  try { grouping = localStorage.getItem('parlera.history.group') || 'unit'; } catch { /* ignore */ }
  mount(main, loading());

  const load = async () => {
    const [all, cur] = await Promise.all([api.get(`/api/sessions?language=${lang}&limit=1000`), api.get(`/api/curriculum/${lang}`)]);
    const archived = all.filter((r) => r.is_archived);
    const rows = view === 'archive' ? archived : all.filter((r) => !r.is_archived);
    // the newest unfinished session per unit + type is the one to continue; older ones are marked as such
    const newestOpen = new Map();
    for (const r of all.filter((x) => x.status === 'active' && !x.is_archived).sort((a, b) => b.last_activity.localeCompare(a.last_activity))) {
      const k = `${r.unit_mode ? r.unit_id : ''}|${r.mode}`;
      if (!newestOpen.has(k)) newestOpen.set(k, r.id);
    }
    const ctx = { newestOpen, cur, reload: load };
    const days = state.settings?.history?.archive_after_days ?? 7;

    const tabs = h('div', { class: 'tabs' },
      h('button', { class: view === 'recent' ? 'active' : '', onclick: () => { view = 'recent'; load(); } }, icon('clock', 15), 'Recent', h('span', { class: 'count' }, all.length - archived.length)),
      h('button', { class: view === 'archive' ? 'active' : '', onclick: () => { view = 'archive'; load(); } }, icon('folder', 15), 'Archive', h('span', { class: 'count' }, archived.length)));
    const groupSwitch = h('div', { class: 'segmented' },
      [['unit', 'By unit'], ['date', 'By date']].map(([g, l]) => h('button', { class: grouping === g ? 'active' : '', onclick: () => { grouping = g; try { localStorage.setItem('parlera.history.group', g); } catch { /* ignore */ } load(); } }, l)));

    let content;
    if (!rows.length) content = view === 'archive' ? empty('folder', 'The archive is empty.') : empty('clock', archived.length ? 'No recent sessions. Older ones are in the archive.' : 'No sessions yet.');
    else if (grouping === 'unit' && view === 'recent') content = byUnit(rows, ctx);
    else content = byDate(rows, ctx);

    mount(main, h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('h1', {}, 'Sessions'), h('div', { class: 'sub' }, `Every ${LANGS[lang].name} session is saved. An unfinished one continues exactly where you stopped; your teacher remembers the whole conversation.`)),
        h('button', { class: 'btn primary', onclick: () => openStartDialog() }, icon('plus', 16), 'New session')),
      h('div', { class: 'row between wrap' }, tabs, view === 'recent' ? groupSwitch : null),
      view === 'archive' ? h('div', { class: 'small muted mb' }, days > 0
        ? `Sessions without activity for ${days} days move here automatically (Settings → Progress & cards). Open, continue or move them back any time.`
        : 'Automatic archiving is off (Settings → Progress & cards). Sessions you archive by hand appear here.') : null,
      content));
  };

  // ---------- grouping: level → unit → sessions ----------
  function byUnit(rows, ctx) {
    const { cur } = ctx;
    const units = new Map(cur.curriculum.units.map((u) => [u.id, u]));
    const groups = new Map();
    const other = [];
    for (const r of rows) {
      if (r.unit_mode && units.has(r.unit_id)) {
        if (!groups.has(r.unit_id)) groups.set(r.unit_id, []);
        groups.get(r.unit_id).push(r);
      } else other.push(r);
    }
    // current unit first, then the most recently used
    const order = [...groups.keys()].sort((a, b) => (b === cur.current_unit_id) - (a === cur.current_unit_id)
      || groups.get(b)[0].last_activity.localeCompare(groups.get(a)[0].last_activity));
    const out = [];
    let lastLevel = null;
    for (const uid of order) {
      const u = units.get(uid);
      const lv = cur.curriculum.levels.find((l) => l.code === u.level);
      if (u.level !== lastLevel) {
        const done = lv.units.filter((x) => cur.progress[x.id]?.status === 'completed').length;
        out.push(h('div', { class: 'level-sep' }, h('span', { class: 'level-pill' }, u.level), h('b', {}, lv.title),
          h('span', { class: 'small muted' }, `${done} of ${lv.units.length} units done`)));
        lastLevel = u.level;
      }
      const num = lv.units.findIndex((x) => x.id === uid) + 1;
      const st = statusFromProgress(u, cur.progress[uid], cur.threshold ?? 0.75);
      out.push(h('div', { class: 'card unit-group' },
        h('div', { class: 'unit-group-head' },
          h('div', { class: 'grow' },
            h('div', { class: 'row' }, h('span', { class: 'tiny faint', style: { fontWeight: 700, letterSpacing: '.05em' } }, `UNIT ${num} OF ${lv.units.length}`),
              uid === cur.current_unit_id ? h('span', { class: 'badge accent' }, 'current unit') : null),
            h('div', { style: { fontWeight: 650, fontSize: '16px' } }, u.title)),
          h('div', { style: { minWidth: '230px' } }, unitChecklist(st, { compact: true }))),
        h('div', { class: 'list' }, groups.get(uid).map((r) => row(r, ctx, true)))));
    }
    if (other.length) {
      out.push(h('div', { class: 'level-sep' }, icon('sparkle', 15), h('b', {}, 'Other sessions'), h('span', { class: 'small muted' }, 'chat breaks, free talk, exams, workshops: not part of a unit')));
      out.push(h('div', { class: 'card unit-group' }, h('div', { class: 'list' }, other.map((r) => row(r, ctx, false)))));
    }
    return h('div', {}, out);
  }

  function byDate(rows, ctx) {
    const groups = {};
    for (const r of rows) {
      const key = new Date(r.created_at).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
      (groups[key] ||= []).push(r);
    }
    return Object.entries(groups).map(([month, items]) => h('div', { class: 'mb' },
      h('div', { class: 'section-label' }, month),
      h('div', { class: 'card', style: { padding: '6px 10px' } }, h('div', { class: 'list' }, items.map((r) => row(r, ctx, false))))));
  }

  // ---------- one session ----------
  function statusOf(r, ctx) {
    if (r.status === 'completed') return { cls: 'good', icon: 'check', label: 'Reviewed', tip: 'Finished with End & review: feedback, mistakes and flashcards are on its review page.' };
    const newest = ctx.newestOpen.get(`${r.unit_mode ? r.unit_id : ''}|${r.mode}`) === r.id || r.is_archived;
    if (!newest) return { cls: '', icon: 'clock', label: 'Older, unfinished', tip: 'You started a newer session of this kind. Continue the newer one; review or archive this one.' };
    if (r.reviewed_before) return { cls: 'accent', icon: 'play', label: 'Continued after review', tip: 'You reopened this session after reviewing it. Press End & review again when you finish.', cont: true };
    return { cls: 'accent', icon: 'play', label: 'Unfinished · continue here', tip: 'Not reviewed yet. Continue it, then press End & review for feedback and flashcards.', cont: true };
  }

  function row(r, ctx, inUnit) {
    const st = statusOf(r, ctx);
    const open = () => navigate(r.status === 'completed' ? `review/${r.id}` : `session/${r.id}`);
    const started = fmtDate(r.created_at, { time: true });
    const meta = [
      `Started ${started}`,
      r.resumes ? `continued ${r.resumes}×` : null,
      r.last_activity && r.last_activity.slice(0, 10) !== r.created_at.slice(0, 10) ? `last ${fmtDate(r.last_activity)}` : null,
      `${r.turns} turn${r.turns === 1 ? '' : 's'}`, fmtDuration(r.duration),
      !inUnit && r.unit_mode && r.unit_level ? `${r.unit_level} · ${r.unit_title}` : null,
    ].filter(Boolean).join(' · ');
    const title = inUnit ? (MODE_TITLE[r.mode] || r.title) : (r.title || 'Session');
    return h('div', { class: `list-item clickable ${st.label.startsWith('Older') ? 'older' : ''}`, onclick: open },
      h('span', { class: 'mode-card', style: { padding: 0, border: 0, background: 'transparent' } }, h('span', { class: 'ic' }, icon(MODE_ICON[r.mode] || 'chat', 17))),
      h('div', { class: 'grow' },
        h('div', { style: { fontWeight: 600 } }, title),
        h('div', { class: 'tiny faint' }, meta),
        r.summary && r.status === 'completed' ? h('div', { class: 'small muted', style: { marginTop: '3px' }, html: renderMarkdown(r.summary).replace(/<\/?p>/g, ' ') }) : null),
      h('span', { class: `badge ${st.cls}`, title: st.tip }, icon(st.icon, 12), st.label),
      h('div', { class: 'row', onclick: (e) => e.stopPropagation() },
        st.cont ? h('button', { class: 'btn sm primary', onclick: () => navigate(`session/${r.id}`) }, 'Continue')
          : r.status === 'completed' ? h('button', { class: 'btn ghost icon sm', title: 'Continue this conversation', onclick: () => navigate(`session/${r.id}`) }, icon('chat', 15)) : null,
        h('button', { class: 'btn ghost icon sm', title: r.is_archived ? 'Move back to recent sessions' : 'Move to the archive', onclick: async () => {
          await api.patch(`/api/sessions/${r.id}`, { archived: !r.is_archived });
          toast(r.is_archived ? 'Moved back to recent sessions' : 'Moved to the archive'); ctx.reload();
        } }, icon(r.is_archived ? 'arrowLeft' : 'folder', 15)),
        h('button', { class: 'btn ghost icon sm', title: 'Rename', onclick: async () => { const t = await promptDialog('Rename session', { value: r.title }); if (t) { await api.patch(`/api/sessions/${r.id}`, { title: t }); ctx.reload(); } } }, icon('edit', 15)),
        h('a', { class: 'btn ghost icon sm', title: 'Export transcript', href: `/api/sessions/${r.id}/export.md` }, icon('download', 15)),
        h('button', { class: 'btn ghost icon sm', title: 'Delete', onclick: async () => {
          if (await confirmDialog('Delete this session and its transcript? Words you saved and your progress are kept.', { danger: true, ok: 'Delete' })) {
            await api.del(`/api/sessions/${r.id}`); toast('Session deleted'); ctx.reload();
          }
        } }, icon('trash', 15))));
  }

  await load();
}
