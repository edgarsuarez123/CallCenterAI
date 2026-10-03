interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: "default" | "indigo" | "emerald" | "amber" | "red" | "slate";
}

const colorClasses = {
  default: "text-slate-900",
  indigo: "text-indigo-600",
  emerald: "text-emerald-600",
  amber: "text-amber-600",
  red: "text-red-600",
  slate: "text-slate-500",
};

export function StatCard({ label, value, sub, color = "default" }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">{label}</p>
      <p className={`mt-1.5 text-3xl font-bold ${colorClasses[color]}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
    </div>
  );
}
