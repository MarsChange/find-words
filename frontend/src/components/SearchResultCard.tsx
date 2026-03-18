import { type SearchResultItem } from '@/services/api';

interface SearchResultCardProps {
  result: SearchResultItem;
  keyword: string;
  traditionalKeyword?: string;
  onViewInReader?: (fileId: number, page: number) => void;
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function highlightKeyword(text: string, keyword: string, traditionalKeyword?: string) {
  if (!keyword) return text;
  const keywords = [keyword];
  if (traditionalKeyword && traditionalKeyword !== keyword) {
    keywords.push(traditionalKeyword);
  }
  const pattern = keywords.map(escapeRegExp).join('|');
  const regex = new RegExp(`(${pattern})`, 'gi');
  const parts = text.split(regex);
  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return parts.map((part, i) =>
    lowerKeywords.includes(part.toLowerCase()) ? (
      <mark key={i} className="bg-cinnabar-400/20 text-cinnabar-600 font-bold rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

export default function SearchResultCard({ result, keyword, traditionalKeyword, onViewInReader }: SearchResultCardProps) {
  const snippets = result.source === 'local'
    ? [result.snippet]
    : (result.snippets && result.snippets.length > 0 ? result.snippets : [result.snippet]);

  return (
    <div className="group rounded-lg border border-parchment-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="mb-2 flex items-center gap-2 text-sm text-parchment-500">
        {result.dynasty && (
          <span className="rounded bg-cinnabar-500/10 px-1.5 py-0.5 font-serif text-cinnabar-600">
            {result.dynasty}
          </span>
        )}
        {result.category && (
          <span className="rounded bg-indigo-500/10 px-1.5 py-0.5 font-serif text-xs text-indigo-600">
            {result.category}
          </span>
        )}
        {result.source === 'local' && (
          <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-xs text-emerald-600">本地</span>
        )}
        {result.source === 'local' && result.is_original_text && (
          <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-xs text-sky-600">正文（联网判定）</span>
        )}
        {result.source === 'local' && !result.is_original_text && (
          <span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-xs text-slate-600">注文</span>
        )}
        {result.source === 'cbeta' && (
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700">CBETA</span>
        )}
        <span className="font-serif font-medium text-ink-800">{result.filename}</span>
        {result.author && (
          <span className="text-parchment-400">
            {result.author}
          </span>
        )}
      </div>

      {snippets.length === 1 ? (
        <p className="font-serif leading-relaxed text-ink-700">
          {highlightKeyword(snippets[0], keyword, traditionalKeyword)}
        </p>
      ) : (
        <div className="space-y-2">
          {snippets.map((s, idx) => (
            <p key={idx} className="font-serif leading-relaxed text-ink-700">
              <span className="mr-1.5 inline-block rounded bg-parchment-200 px-1.5 py-0.5 text-xs text-parchment-500">
                {idx + 1}
              </span>
              {highlightKeyword(s, keyword, traditionalKeyword)}
            </p>
          ))}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between">
        {result.page_num != null && (
          <span className="text-xs text-parchment-400">
            第 {result.page_num} 页
          </span>
        )}
        {onViewInReader && result.file_id != null && result.page_num != null && (
          <button
            onClick={() => onViewInReader(result.file_id!, result.page_num!)}
            className="text-xs text-cinnabar-500 opacity-0 transition-opacity hover:underline group-hover:opacity-100"
          >
            在阅读器中查看
          </button>
        )}
      </div>
    </div>
  );
}
