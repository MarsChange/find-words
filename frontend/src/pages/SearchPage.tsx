import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import SearchResultCard from '@/components/SearchResultCard';
import ChatSidebar from '@/components/ChatSidebar';
import { createSession, getSession, getSessionResults, type SearchResultItem } from '@/services/api';
import { wsService } from '@/services/websocket';

export default function SearchPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [useCbeta, setUseCbeta] = useState(false);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [sessionId, setSessionId] = useState<number | undefined>();
  const [traditionalKeyword, setTraditionalKeyword] = useState('');
  const [synthesis, setSynthesis] = useState('');
  const [isSynthesizing, setIsSynthesizing] = useState(false);

  // Connect WebSocket on mount
  useEffect(() => {
    wsService.connect();
    
    // Listen for search events
    const unsubStarted = wsService.on('search_started', () => {
      setIsSynthesizing(false);
      setSynthesis('');
    });
    
    const unsubChunk = wsService.on('synthesis_chunk', (data) => {
      setIsSynthesizing(true);
      setSynthesis((prev) => prev + (data.chunk as string || ''));
    });
    
    const unsubComplete = wsService.on('search_complete', (data) => {
      setIsSynthesizing(false);
      setIsSearching(false);
      setResults((data.hits as SearchResultItem[]) || []);
      setTotal((data.hits as SearchResultItem[])?.length || 0);
      setTraditionalKeyword((data.traditional_query as string) || '');
      setSynthesis((data.synthesis as string) || '');
    });
    
    const unsubError = wsService.on('search_error', () => {
      setIsSearching(false);
      setIsSynthesizing(false);
      setResults([]);
      setTotal(0);
    });
    
    return () => {
      unsubStarted();
      unsubChunk();
      unsubComplete();
      unsubError();
    };
  }, []);

  const doSearch = useCallback(async () => {
    const q = keyword.trim();
    if (!q) return;
    setIsSearching(true);
    setHasSearched(true);
    setSynthesis('');
    setIsSynthesizing(false);
    try {
      // Create a new chat session for this search
      const session = await createSession(q);
      setSessionId(session.id);

      // Send search request via WebSocket
      wsService.send({
        type: 'search_stream',
        query: q,
        use_cbeta: useCbeta,
        session_id: session.id,
      });
    } catch {
      setResults([]);
      setTotal(0);
      setIsSearching(false);
    }
  }, [keyword, useCbeta]);

  const handleViewInReader = (fileId: number, page: number) => {
    navigate(`/reader/${fileId}?page=${page}&keyword=${encodeURIComponent(keyword)}`);
  };

  const handleSessionChange = async (newSessionId: number | undefined) => {
    setSessionId(newSessionId);
    if (!newSessionId) {
      setKeyword('');
      setTraditionalKeyword('');
      setResults([]);
      setTotal(0);
      setHasSearched(false);
      return;
    }
    // Restore keyword and results from the historical session
    try {
      const [sessionData, savedResults] = await Promise.all([
        getSession(newSessionId),
        getSessionResults(newSessionId),
      ]);
      setKeyword(sessionData.session.keyword);
      setTraditionalKeyword(sessionData.session.traditional_keyword || '');
      setSynthesis(sessionData.session.synthesis || '');
      setResults(savedResults);
      setTotal(savedResults.length);
      setHasSearched(true);
    } catch {
      // If loading fails, just switch session without restoring
    }
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Search bar */}
        <div className="border-b border-parchment-200 bg-white px-6 py-4">
          <div className="mx-auto flex max-w-2xl gap-3">
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
              placeholder="输入检索词语..."
              className="flex-1 rounded-lg border border-parchment-200 bg-parchment-50 px-4 py-2.5 font-serif text-ink-800 placeholder:text-parchment-400 focus:border-cinnabar-400 focus:outline-none focus:ring-2 focus:ring-cinnabar-400/20"
            />
            <button
              onClick={doSearch}
              disabled={isSearching}
              className="rounded-lg bg-cinnabar-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-cinnabar-600 disabled:opacity-50"
            >
              {isSearching ? '检索中...' : '检索'}
            </button>
          </div>
          <div className="mx-auto mt-2 flex max-w-2xl items-center">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-700">
              <input
                type="checkbox"
                checked={useCbeta}
                onChange={(e) => setUseCbeta(e.target.checked)}
                className="h-4 w-4 rounded border-parchment-300 text-cinnabar-500 focus:ring-cinnabar-400"
              />
              同时检索 CBETA 线上佛典
            </label>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-6">
          {!hasSearched && (
            <div className="flex h-full flex-col items-center justify-center text-parchment-400">
              <svg className="mb-4 h-16 w-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <p className="font-serif text-lg">输入关键词，探索古籍世界</p>
            </div>
          )}

          {hasSearched && !isSearching && results.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center text-parchment-400">
              <p className="font-serif text-lg">未找到相关结果</p>
              <p className="mt-1 text-sm">请尝试其他关键词</p>
            </div>
          )}

          {hasSearched && results.length > 0 && (
            <>
              {/* AI Analysis Section */}
              {(synthesis || isSynthesizing) && (
                <div className="mb-6 rounded-lg border border-cinnabar-200 bg-gradient-to-r from-parchment-50 to-white p-4 shadow-sm">
                  <div className="mb-2 flex items-center gap-2">
                    <svg className="h-5 w-5 text-cinnabar-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                        d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" 
                      />
                    </svg>
                    <h3 className="font-serif font-semibold text-ink-800">AI 词源分析</h3>
                    {isSynthesizing && (
                      <div className="ml-auto flex items-center gap-1.5 text-xs text-cinnabar-600">
                        <div className="h-2 w-2 animate-pulse rounded-full bg-cinnabar-500"></div>
                        生成中...
                      </div>
                    )}
                  </div>
                  <div className="prose prose-sm max-w-none font-serif text-ink-700 prose-headings:text-ink-800 prose-strong:text-ink-800 prose-a:text-cinnabar-600">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{synthesis}</ReactMarkdown>
                    {isSynthesizing && (
                      <span className="inline-block h-4 w-1 animate-pulse bg-cinnabar-500"></span>
                    )}
                  </div>
                </div>
              )}
              
              <p className="mb-4 text-sm text-parchment-400">
                共找到 <span className="font-medium text-ink-700">{total}</span> 条结果
              </p>
              <div className="space-y-3">
                {results.map((r, i) => (
                  <SearchResultCard
                    key={i}
                    result={r}
                    keyword={keyword}
                    traditionalKeyword={traditionalKeyword}
                    onViewInReader={handleViewInReader}
                  />
                ))}
              </div>
            </>
          )}

          {isSearching && (
            <div className="flex h-full items-center justify-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-parchment-300 border-t-cinnabar-500" />
            </div>
          )}
        </div>
      </div>

      {/* AI sidebar */}
      <ChatSidebar
        keyword={keyword}
        traditionalKeyword={traditionalKeyword}
        sessionId={sessionId}
        synthesis={synthesis}
        onSessionChange={handleSessionChange}
      />
    </div>
  );
}
