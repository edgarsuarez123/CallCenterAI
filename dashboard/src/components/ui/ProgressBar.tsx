interface ProgressBarProps {
  pct: number;
  showLabel?: boolean;
  height?: "sm" | "md" | "lg";
}

const heightClasses = { sm: "h-1.5", md: "h-2", lg: "h-3" };

export function ProgressBar({ pct, showLabel = false, height = "md" }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, pct));
  const color =
    clamped === 100
      ? "bg-emerald-500"
      : clamped > 50
      ? "bg-indigo-500"
      : clamped > 0
      ? "bg-indigo-400"
      : "bg-slate-200";

  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 bg-slate-100 rounded-full overflow-hidden ${heightClasses[height]}`}>
        <div
          className={`${heightClasses[height]} rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs font-medium text-slate-500 w-9 text-right">
          {Math.round(clamped)}%
        </span>
      )}
    </div>
  );
}
