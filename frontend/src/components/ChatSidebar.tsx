import { useState, useRef, useEffect, useCallback } from 'react';
import SessionList from '@/components/SessionList';
import {
  chat,
  getSessions,
  getSession,
  deleteSession as apiDeleteSession,
  type Session,
  type ChatMessage,
} from '@/services/api';

interface ChatSidebarProps {
  keyword?: string;
  sessionId?: number;
  onSessionChange?: (sessionId: number | undefined) => void;
}

export default function ChatSidebar({ sessionId, onSessionChange }: ChatSidebarProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load sessions list
  const loadSessions = useCallback(async () => {
    try {
      const data = await getSessions();
      setSessions(data);
    } catch {
      // silently fail
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // When sessionId changes, load that session's messages
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    getSession(sessionId)
      .then((data) => {
        if (!cancelled) {
          setMessages(
            data.messages.map((m) => ({ role: m.role, content: m.content }))
          );
        }
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  const handleSelectSession = (session: Session) => {
    onSessionChange?.(session.id);
  };

  const handleDeleteSession = async (sid: number) => {
    try {
      await apiDeleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (sid === sessionId) {
        onSessionChange?.(undefined);
        setMessages([]);
      }
    } catch {
      // silently fail
    }
  };

  const handleNewSession = () => {
    onSessionChange?.(undefined);
    setMessages([]);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const data = await chat({
        message: text,
        session_id: sessionId,
        history: messages,
      });
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
      // Refresh sessions list to pick up updated timestamps / message counts
      loadSessions();
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '抱歉，请求出错，请稍后重试。' },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 rounded-full bg-cinnabar-500 p-3 text-white shadow-lg transition-transform hover:scale-105"
        title="打开 AI 助手"
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
          />
        </svg>
      </button>
    );
  }

  return (
    <aside className="flex h-full w-80 flex-col border-l border-parchment-200 bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-parchment-200 px-4 py-3">
        <h3 className="font-serif text-sm font-semibold text-ink-800">AI 助手</h3>
        <button
          onClick={() => setIsOpen(false)}
          className="text-parchment-400 transition-colors hover:text-ink-700"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Session history */}
      <SessionList
        sessions={sessions}
        activeSessionId={sessionId}
        onSelect={handleSelectSession}
        onDelete={handleDeleteSession}
        onNewSession={handleNewSession}
      />

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-center text-sm text-parchment-400">
            输入问题，AI 助手将结合检索结果为您解答。
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-lg px-3 py-2 text-sm ${
              msg.role === 'user'
                ? 'ml-4 bg-cinnabar-500 text-white'
                : 'mr-4 bg-parchment-100 text-ink-800'
            }`}
          >
            {msg.content}
          </div>
        ))}
        {isLoading && (
          <div className="mr-4 rounded-lg bg-parchment-100 px-3 py-2 text-sm text-parchment-400">
            思考中...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-parchment-200 p-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="输入问题..."
            className="flex-1 rounded-md border border-parchment-200 bg-parchment-50 px-3 py-1.5 text-sm text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-1 focus:ring-cinnabar-400"
          />
          <button
            onClick={sendMessage}
            disabled={isLoading}
            className="rounded-md bg-cinnabar-500 px-3 py-1.5 text-sm text-white transition-colors hover:bg-cinnabar-600 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </aside>
  );
}
