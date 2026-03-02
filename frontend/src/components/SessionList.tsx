import { type Session } from '@/services/api';

interface SessionListProps {
  sessions: Session[];
  activeSessionId?: number;
  onSelect: (session: Session) => void;
  onDelete: (sessionId: number) => void;
  onNewSession: () => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hour = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${min}`;
}

export default function SessionList({
  sessions,
  activeSessionId,
  onSelect,
  onDelete,
  onNewSession,
}: SessionListProps) {
  return (
    <div className="flex flex-col border-b border-parchment-200">
      {/* Header with new session button */}
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium text-parchment-400">历史会话</span>
        <button
          onClick={onNewSession}
          className="rounded px-1.5 py-0.5 text-xs text-cinnabar-500 transition-colors hover:bg-cinnabar-500/10"
        >
          + 新建
        </button>
      </div>

      {/* Session list */}
      <div className="max-h-48 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="px-3 pb-2 text-xs text-parchment-400">暂无历史会话</p>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                className={`group flex cursor-pointer items-center justify-between px-3 py-1.5 text-xs transition-colors ${
                  isActive
                    ? 'bg-cinnabar-500/10 text-cinnabar-600'
                    : 'text-ink-700 hover:bg-parchment-100'
                }`}
                onClick={() => onSelect(session)}
              >
                <span className="truncate">
                  <span className="font-serif">{'\u3010'}{session.keyword}{'\u3011'}</span>
                  {' '}
                  <span className="text-parchment-400">{formatTime(session.created_at)}</span>
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm('确认删除此会话？')) {
                      onDelete(session.id);
                    }
                  }}
                  className="ml-1 shrink-0 text-parchment-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                >
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
