import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import SearchResultCard from '@/components/SearchResultCard';
import ChatSidebar from '@/components/ChatSidebar';
import { search, createSession, type SearchResultItem } from '@/services/api';

export default function SearchPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [sessionId, setSessionId] = useState<number | undefined>();

  const doSearch = useCallback(async () => {
    const q = keyword.trim();
    if (!q) return;
    setIsSearching(true);
    setHasSearched(true);
    try {
      // Create a new chat session for this search
      const session = await createSession(q);
      setSessionId(session.id);

      const data = await search({ keyword: q });
      setResults(data.hits);
      setTotal(data.total);
    } catch {
      setResults([]);
      setTotal(0);
    } finally {
      setIsSearching(false);
    }
  }, [keyword]);

  const handleViewInReader = (fileId: number, page: number) => {
    navigate(`/reader/${fileId}?page=${page}&keyword=${encodeURIComponent(keyword)}`);
  };

  const handleSessionChange = (newSessionId: number | undefined) => {
    setSessionId(newSessionId);
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
              <p className="mb-4 text-sm text-parchment-400">
                共找到 <span className="font-medium text-ink-700">{total}</span> 条结果
              </p>
              <div className="space-y-3">
                {results.map((r, i) => (
                  <SearchResultCard
                    key={i}
                    result={r}
                    keyword={keyword}
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
        sessionId={sessionId}
        onSessionChange={handleSessionChange}
      />
    </div>
  );
}
