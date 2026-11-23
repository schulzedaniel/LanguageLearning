// Session history: resume unfinished sessions, open reviews, export, delete.
import { renderMarkdown } from '../markdown.js';
import { api, state, LANGS } from '../api.js';
import { h, icon, mount, loading, toast, confirmDialog, fmtDate, fmtDuration, empty, promptDialog } from '../ui.js';
import { navigate } from '../nav.js';
import { openStartDialog } from './start.js';

const MODE_ICON = { lesson: 'school', conversation: 'chat', roleplay: 'theater', review: 'refresh', exam: 'award', writing: 'pen', placement: 'compass', free: 'sparkle', pronunciation: 'wave', workshop: 'target', break: 'coffee' };

export default async function history(main) {
  const lang = state.language;
  mount(main, loading());
  const load = async () => {
    const rows = await api.get(`/api/sessions?language=${lang}`);
    const groups = {};
    for (const r of rows) {
      const key = new Date(r.created_at).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
      (groups[key] ||= []).push(r);
    }
    mount(main, h('div', { class: 'page' },
      h('div', { class: 'page-head' },
        h('div', {}, h('h1', {}, 'Sessions'), h('div', { class: 'sub' }, `Every ${LANGS[lang].name} session is saved automatically. Unfinished ones can be resumed — the tutor remembers the whole conversation.`)),
        h('button', { class: 'btn primary', onclick: () => openStartDialog() }, icon('plus', 16), 'New session')),
      rows.length ? Object.entries(groups).map(([month, items]) => h('div', { class: 'mb' },
        h('div', { class: 'section-label' }, month),
        h('div', { class: 'card', style: { padding: '6px 10px' } }, h('div', { class: 'list' }, items.map((r) => row(r))))))
        : empty('clock', 'No sessions yet.')));
  };

  function row(r) {
    const open = () => navigate(r.status === 'completed' ? `review/${r.id}` : `session/${r.id}`);
    return h('div', { class: 'list-item clickable', onclick: open },
      h('span', { class: 'mode-card', style: { padding: 0, border: 0, background: 'transparent' } }, h('span', { class: 'ic' }, icon(MODE_ICON[r.mode] || 'chat', 17))),
      h('div', { class: 'grow' },
        h('div', { style: { fontWeight: 600 } }, r.title || 'Session'),
        h('div', { class: 'tiny faint' }, [fmtDate(r.created_at, { time: true }), fmtDuration(r.duration), `${r.turns} turns`, r.unit_level ? `${r.unit_level} · ${r.unit_title}` : null].filter(Boolean).join(' · ')),
        r.summary ? h('div', { class: 'small muted', style: { marginTop: '3px' }, html: renderMarkdown(r.summary).replace(/<\/?p>/g, ' ') }) : null),
      r.status === 'active' ? h('span', { class: 'badge warn' }, 'In progress') : h('span', { class: 'badge good' }, icon('check', 12), 'Reviewed'),
      h('div', { class: 'row', onclick: (e) => e.stopPropagation() },
        r.status === 'completed' ? h('button', { class: 'btn ghost icon sm', title: 'Continue this conversation', onclick: () => navigate(`session/${r.id}`) }, icon('chat', 15)) : null,
        h('button', { class: 'btn ghost icon sm', title: 'Rename', onclick: async () => { const t = await promptDialog('Rename session', { value: r.title }); if (t) { await api.patch(`/api/sessions/${r.id}`, { title: t }); load(); } } }, icon('edit', 15)),
        h('a', { class: 'btn ghost icon sm', title: 'Export transcript', href: `/api/sessions/${r.id}/export.md` }, icon('download', 15)),
        h('button', { class: 'btn ghost icon sm', title: 'Delete', onclick: async () => {
          if (await confirmDialog('Delete this session and its transcript? Words you saved and your progress are kept.', { danger: true, ok: 'Delete' })) {
            await api.del(`/api/sessions/${r.id}`); toast('Session deleted'); load();
          }
        } }, icon('trash', 15))));
  }
  await load();
}
