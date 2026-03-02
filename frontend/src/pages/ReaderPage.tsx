import { useParams, useSearchParams } from 'react-router-dom';
import { Viewer, Worker } from '@react-pdf-viewer/core';
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout';
import { searchPlugin } from '@react-pdf-viewer/search';
import { getFileUrl } from '@/services/api';
import '@react-pdf-viewer/core/lib/styles/index.css';
import '@react-pdf-viewer/default-layout/lib/styles/index.css';
import '@react-pdf-viewer/search/lib/styles/index.css';

export default function ReaderPage() {
  const { fileId } = useParams<{ fileId: string }>();
  const [searchParams] = useSearchParams();
  const initialPage = parseInt(searchParams.get('page') || '1', 10) - 1;
  const keyword = searchParams.get('keyword') || '';

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
    <div className="h-[calc(100vh-3.5rem)]">
      <Worker workerUrl="https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js">
        <Viewer
          fileUrl={fileUrl}
          initialPage={initialPage}
          plugins={[defaultLayoutPluginInstance, searchPluginInstance]}
        />
      </Worker>
    </div>
  );
}
