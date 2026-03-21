import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Viewer, Worker } from '@react-pdf-viewer/core';
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout';
import { searchPlugin } from '@react-pdf-viewer/search';
import { getFileUrl } from '@/services/api';
import '@react-pdf-viewer/core/lib/styles/index.css';
import '@react-pdf-viewer/default-layout/lib/styles/index.css';
import '@react-pdf-viewer/search/lib/styles/index.css';

export default function ReaderPage() {
  const navigate = useNavigate();
  const { fileId } = useParams<{ fileId: string }>();
  const [searchParams] = useSearchParams();
  const initialPage = parseInt(searchParams.get('page') || '1', 10) - 1;
  const keyword = searchParams.get('keyword') || '';
  const sessionId = searchParams.get('session_id') || '';

  const handleBackToSearch = () => {
    if (sessionId) {
      navigate(`/?session_id=${encodeURIComponent(sessionId)}`);
      return;
    }
    if (window.history.length > 1) {
      navigate(-1);
      return;
    }
    navigate('/');
  };

  const searchPluginInstance = searchPlugin({
    keyword: keyword ? [keyword] : [],
  });

  const defaultLayoutPluginInstance = defaultLayoutPlugin({
    toolbarPlugin: {
      searchPlugin: {
        keyword: keyword ? [keyword] : [],
      },
    },
  });

  if (!fileId) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center text-parchment-400">
        <p className="font-serif">未指定文件</p>
      </div>
    );
  }

  const fileUrl = getFileUrl(fileId);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="flex items-center justify-between border-b border-parchment-200 bg-white px-4 py-2">
        <button
          type="button"
          onClick={handleBackToSearch}
          className="rounded-md border border-parchment-200 px-3 py-1.5 text-sm text-ink-700 transition-colors hover:bg-parchment-100"
        >
          返回检索结果
        </button>
        {keyword && (
          <span className="text-xs text-parchment-400">
            关键词：{keyword}
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        <Worker workerUrl="https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js">
          <Viewer
            fileUrl={fileUrl}
            initialPage={initialPage}
            plugins={[defaultLayoutPluginInstance, searchPluginInstance]}
          />
        </Worker>
      </div>
    </div>
  );
}
