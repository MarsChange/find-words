interface ProgressBarProps {
  progress: number; // 0–100
  label?: string;
  status?: 'indexing' | 'completed' | 'error';
}

export default function ProgressBar({ progress, label, status = 'indexing' }: ProgressBarProps) {
  const barColor =
    status === 'error'
      ? 'bg-red-400'
      : status === 'completed'
      ? 'bg-green-500'
      : 'bg-cinnabar-500';

  const statusText =
    status === 'error'
      ? '索引失败'
      : status === 'completed'
      ? '索引完成'
      : '索引中...';

  return (
    <div className="w-full">
      {label && (
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="truncate text-ink-700">{label}</span>
          <span className="text-parchment-400">{statusText}</span>
        </div>
      )}
      <div className="h-2 w-full overflow-hidden rounded-full bg-parchment-200">
        <div
          className={`h-full rounded-full transition-all duration-300 ease-out ${barColor}`}
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
      </div>
      <div className="mt-0.5 text-right text-xs text-parchment-400">
        {Math.round(progress)}%
      </div>
    </div>
  );
}
