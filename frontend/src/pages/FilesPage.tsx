import { useState, useEffect, useCallback } from 'react';
import FileUploader from '@/components/FileUploader';
import ProgressBar from '@/components/ProgressBar';
import { listFiles, uploadFiles, deleteFile, reindexFile, type FileInfo } from '@/services/api';
import { wsService } from '@/services/websocket';

interface FileProgress {
  current: number;
  total: number;
}

export default function FilesPage() {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState<Record<number, FileProgress>>({});

  const loadFiles = useCallback(async () => {
    try {
      const data = await listFiles();
      setFiles(data);
    } catch {
      // silently fail on initial load
    }
  }, []);

  useEffect(() => {
    loadFiles();

    // Listen for indexing progress via WebSocket
    wsService.connect();
    const unsub = wsService.on('index_progress', (data) => {
      const fileId = data.file_id as number;
      const status = data.status as string | undefined;
      const current = data.current as number | undefined;
      const total = data.total as number | undefined;

      // Update progress
      if (current != null && total != null && total > 0) {
        setProgress((prev) => ({ ...prev, [fileId]: { current, total } }));
      }

      // Update file status when completed or errored
      if (status === 'ready' || status === 'error') {
        setProgress((prev) => {
          const next = { ...prev };
          delete next[fileId];
          return next;
        });
        // Reload file list to get updated page_count and status
        loadFiles();
      }
    });

    return () => {
      unsub();
    };
  }, [loadFiles]);

  const handleUpload = async (selectedFiles: File[]) => {
    setIsUploading(true);
    try {
      await uploadFiles(selectedFiles);
      await loadFiles();
    } catch {
      alert('上传失败，请重试。');
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async (fileId: number) => {
    if (!confirm('确认删除此文件？')) return;
    try {
      await deleteFile(fileId);
      setFiles((prev) => prev.filter((f) => f.id !== fileId));
    } catch {
      alert('删除失败。');
    }
  };

  const handleReindex = async (fileId: number) => {
    try {
      await reindexFile(fileId);
      setFiles((prev) =>
        prev.map((f) => (f.id === fileId ? { ...f, status: 'processing' } : f))
      );
    } catch {
      alert('重新索引失败。');
    }
  };

  const getProgressPercent = (fileId: number): number => {
    const p = progress[fileId];
    if (!p || p.total === 0) return 0;
    return Math.round((p.current / p.total) * 100);
  };

  const getProgressLabel = (fileId: number): string => {
    const p = progress[fileId];
    if (!p) return '';
    return `${p.current} / ${p.total} 页`;
  };

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="mb-6 font-serif text-2xl font-semibold text-ink-800">文件管理</h1>

      {/* Upload area */}
      <div className="mb-8">
        <FileUploader onUpload={handleUpload} />
        {isUploading && (
          <p className="mt-2 text-center text-sm text-parchment-400">上传中，请稍候...</p>
        )}
      </div>

      {/* File list */}
      {files.length === 0 ? (
        <p className="text-center text-sm text-parchment-400">暂无文件，请上传古籍文档。</p>
      ) : (
        <div className="space-y-3">
          {files.map((file) => (
            <div
              key={file.id}
              className="rounded-lg border border-parchment-200 bg-white p-4 shadow-sm"
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <svg className="h-5 w-5 text-cinnabar-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <div>
                    <p className="text-sm font-medium text-ink-800">{file.filename}</p>
                    <p className="text-xs text-parchment-400">
                      {file.dynasty && `${file.dynasty}`}
                      {file.author && ` · ${file.author}`}
                      {file.page_count > 0 && ` · ${file.page_count} 页已索引`}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleReindex(file.id)}
                    disabled={file.status === 'processing' || file.status === 'indexing'}
                    className="text-xs text-parchment-400 transition-colors hover:text-cinnabar-500 disabled:opacity-40"
                  >
                    重新索引
                  </button>
                  <button
                    onClick={() => handleDelete(file.id)}
                    className="text-xs text-parchment-400 transition-colors hover:text-red-500"
                  >
                    删除
                  </button>
                </div>
              </div>

              {(file.status === 'indexing' || file.status === 'pending' || file.status === 'processing') && (
                <ProgressBar
                  progress={getProgressPercent(file.id)}
                  label={getProgressLabel(file.id) || undefined}
                  status="indexing"
                />
              )}
              {(file.status === 'completed' || file.status === 'ready') && (
                <ProgressBar progress={100} status="completed" />
              )}
              {file.status === 'error' && (
                <ProgressBar progress={0} status="error" />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
