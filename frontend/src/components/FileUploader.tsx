import { useState, useRef, useCallback } from 'react';

interface FileUploaderProps {
  onUpload: (files: File[]) => void;
  accept?: string;
}

export default function FileUploader({ onUpload, accept = '.pdf,.txt' }: FileUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) onUpload(files);
    },
    [onUpload]
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length > 0) onUpload(files);
      if (fileInputRef.current) fileInputRef.current.value = '';
    },
    [onUpload]
  );

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => fileInputRef.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors ${
        isDragging
          ? 'border-cinnabar-400 bg-cinnabar-500/5'
          : 'border-parchment-300 bg-parchment-50 hover:border-parchment-400 hover:bg-parchment-100'
      }`}
    >
      <svg className="mb-3 h-10 w-10 text-parchment-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
        />
      </svg>
      <p className="text-sm text-ink-700">
        拖拽文件到此处，或 <span className="text-cinnabar-500 underline">点击选择</span>
      </p>
      <p className="mt-1 text-xs text-parchment-400">支持 PDF、TXT 格式</p>

      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        multiple
        onChange={handleFileSelect}
        className="hidden"
      />
    </div>
  );
}
