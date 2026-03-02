import { type SearchResultItem } from '@/services/api';

interface SearchResultCardProps {
  result: SearchResultItem;
  keyword: string;
  onViewInReader?: (fileId: number, page: number) => void;
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightKeyword(text: string, keyword: string) {
  if (!keyword) return text;
  const escaped = escapeRegExp(keyword);
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === keyword.toLowerCase() ? (
      <mark key={i} className="bg-cinnabar-400/20 text-cinnabar-600 rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

export default function SearchResultCard({ result, keyword, onViewInReader }: SearchResultCardProps) {
  return (
    <div className="group rounded-lg border border-parchment-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="mb-2 flex items-center gap-2 text-sm text-parchment-500">
        {result.dynasty && (
          <span className="rounded bg-cinnabar-500/10 px-1.5 py-0.5 font-serif text-cinnabar-600">
            {result.dynasty}
          </span>
        )}
        <span className="font-serif font-medium text-ink-800">{result.filename}</span>
        {result.author && (
          <span className="text-parchment-400">
            {result.author}
          </span>
        )}
      </div>

      <p className="font-serif leading-relaxed text-ink-700">
        {highlightKeyword(result.snippet, keyword)}
      </p>

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
