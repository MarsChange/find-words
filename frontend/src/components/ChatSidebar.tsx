import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import SessionList from '@/components/SessionList';
import { highlightKeyword } from '@/components/SearchResultCard';
import {
  getSessions,
  getSession,
  getSessionResults,
  deleteSession as apiDeleteSession,
  type Session,
  type ChatMessage,
  type SearchResultItem,
} from '@/services/api';
import { wsService } from '@/services/websocket';

interface ChatSidebarProps {
  keyword?: string;
  traditionalKeyword?: string;
  sessionId?: number;
  synthesis?: string;
  onSessionChange?: (sessionId: number | undefined) => void;
}

function expandLocalResults(items: SearchResultItem[]): SearchResultItem[] {
  return items.flatMap((item) => {
    if (item.source !== 'local') return [item];
    const snippets = item.snippets && item.snippets.length > 0 ? item.snippets : [];
    if (snippets.length <= 1) {
      return [{ ...item, snippet: snippets[0] ?? item.snippet, snippets: undefined }];
    }
    return snippets.map((snippet) => ({
      ...item,
      snippet,
      snippets: undefined,
    }));
  });
}

/* ── Collapsible search results panel ── */

function SessionResultsPanel({ sessionId, keyword, traditionalKeyword }: { sessionId: number; keyword?: string; traditionalKeyword?: string }) {
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setResults([]);
    setIsExpanded(false);
    setLoaded(false);
  }, [sessionId]);

  const handleToggle = async () => {
    if (!loaded) {
      setIsLoading(true);
      try {
        const data = await getSessionResults(sessionId);
        setResults(expandLocalResults(data));
      } catch {
        setResults([]);
      } finally {
        setIsLoading(false);
        setLoaded(true);
      }
    }
    setIsExpanded((prev) => !prev);
  };

  const localResults = results.filter((r) => r.source === 'local');
  const cbetaResults = results.filter((r) => r.source === 'cbeta');

  return (
    <div className="border-b border-parchment-200">
      <button
        onClick={handleToggle}
        className="flex w-full items-center justify-between px-4 py-2 text-xs text-ink-700 transition-colors hover:bg-parchment-100"
      >
        <span className="flex items-center gap-1.5 font-medium">
          <svg
            className={`h-3 w-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          检索条目
          {loaded && (
            <span className="text-parchment-400">({results.length})</span>
          )}
        </span>
        {isLoading && (
          <span className="h-3 w-3 animate-spin rounded-full border border-parchment-300 border-t-cinnabar-500" />
        )}
      </button>

      {isExpanded && loaded && (
        <div className="max-h-64 overflow-y-auto px-3 pb-2">
          {results.length === 0 ? (
            <p className="py-2 text-center text-xs text-parchment-400">暂无检索条目</p>
          ) : (
            <>
              {localResults.length > 0 && (
                <div className="mb-2">
                  <p className="mb-1 text-xs font-medium text-ink-600">本地文献</p>
                  <div className="space-y-1">
                    {localResults.map((r, i) => (
                      <ResultItem key={`local-${i}`} result={r} keyword={keyword} traditionalKeyword={traditionalKeyword} />
                    ))}
                  </div>
                </div>
              )}
              {cbetaResults.length > 0 && (
                <div>
                  <p className="mb-1 text-xs font-medium text-cinnabar-600">CBETA 佛典</p>
                  <div className="space-y-1">
                    {cbetaResults.map((r, i) => (
                      <ResultItem key={`cbeta-${i}`} result={r} keyword={keyword} traditionalKeyword={traditionalKeyword} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ResultItem({ result, keyword, traditionalKeyword }: { result: SearchResultItem; keyword?: string; traditionalKeyword?: string }) {
  const isCbeta = result.source === 'cbeta';
  const snippetCount = result.snippets && result.snippets.length > 0 ? result.snippets.length : 0;
  const displaySnippet = result.snippets && result.snippets.length > 0 ? result.snippets[0] : result.snippet;

  return (
    <div className="rounded border border-parchment-200 bg-parchment-50 px-2 py-1.5 text-xs">
      <div className="flex items-center gap-1.5">
        {result.dynasty && (
          <span className="rounded bg-cinnabar-500/10 px-1 py-0.5 font-serif text-cinnabar-600">
            {result.dynasty}
          </span>
        )}
        {result.source === 'local' && (
          <span className="rounded bg-emerald-500/10 px-1 py-0.5 text-emerald-600">本地</span>
        )}
        {result.source === 'local' && !result.is_original_text && (
          <span className="rounded bg-slate-500/10 px-1 py-0.5 text-slate-600">注文</span>
        )}
        {result.source === 'local' && result.is_original_text && (
          <span className="rounded bg-sky-500/10 px-1 py-0.5 text-sky-600">正文</span>
        )}
        {isCbeta && (
          <span className="rounded bg-amber-500/10 px-1 py-0.5 text-amber-700">CBETA</span>
        )}
        <span className="truncate font-serif font-medium text-ink-800">{result.filename}</span>
      </div>
      {result.author && (
        <span className="text-parchment-400">{result.author}</span>
      )}
      <p className="mt-0.5 line-clamp-2 font-serif leading-snug text-ink-700">
        {keyword ? highlightKeyword(displaySnippet, keyword, traditionalKeyword) : displaySnippet}
      </p>
      {snippetCount > 1 && (
        <p className="mt-0.5 text-parchment-400">共 {snippetCount} 筆</p>
      )}
    </div>
  );
}

/* ── Main ChatSidebar ── */

export default function ChatSidebar({ keyword, traditionalKeyword, sessionId, synthesis, onSessionChange }: ChatSidebarProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(true);
  const [streamingMessage, setStreamingMessage] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

  // Setup WebSocket listeners for chat
  useEffect(() => {
    const unsubStarted = wsService.on('chat_started', () => {
      setIsLoading(true);
      setStreamingMessage('');
    });
    
    const unsubChunk = wsService.on('chat_chunk', (data) => {
      setStreamingMessage((prev) => prev + (data.chunk as string || ''));
    });
    
    const unsubComplete = wsService.on('chat_complete', (data) => {
      setIsLoading(false);
      const reply = data.reply as string;
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
      setStreamingMessage('');
      loadSessions();
    });
    
    const unsubError = wsService.on('chat_error', () => {
      setIsLoading(false);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '抱歉，请求出错，请稍后重试。' },
      ]);
      setStreamingMessage('');
    });
    
    return () => {
      unsubStarted();
      unsubChunk();
      unsubComplete();
      unsubError();
    };
  }, []);

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
    setStreamingMessage('');

    // Send chat request via WebSocket
    wsService.send({
      type: 'chat_stream',
      message: text,
      session_id: sessionId,
      history: messages,
      synthesis: synthesis || '',
    });
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

      {/* Search results for active session (collapsed by default) */}
      {sessionId && <SessionResultsPanel sessionId={sessionId} keyword={keyword} traditionalKeyword={traditionalKeyword} />}

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
            {msg.role === 'assistant' ? (
              <div className="prose prose-sm max-w-none prose-headings:text-ink-800 prose-strong:text-ink-800 prose-p:my-1 prose-li:my-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              </div>
            ) : msg.content}
          </div>
        ))}
        {streamingMessage && (
          <div className="mr-4 rounded-lg bg-parchment-100 px-3 py-2 text-sm text-ink-800">
            <div className="prose prose-sm max-w-none prose-headings:text-ink-800 prose-strong:text-ink-800 prose-p:my-1 prose-li:my-0">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingMessage}</ReactMarkdown>
            </div>
            <span className="inline-block h-4 w-1 animate-pulse bg-cinnabar-500 ml-0.5"></span>
          </div>
        )}
        {isLoading && !streamingMessage && (
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
