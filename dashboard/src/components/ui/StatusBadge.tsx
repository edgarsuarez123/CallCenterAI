const statusColors: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  queued: "bg-amber-50 text-amber-700",
  running: "bg-indigo-50 text-indigo-700",
  paused: "bg-orange-50 text-orange-700",
  completed: "bg-emerald-50 text-emerald-700",
  cancelled: "bg-red-50 text-red-700",
  // Contact outcomes
  accepted: "bg-emerald-50 text-emerald-700",
  declined: "bg-red-50 text-red-700",
  voicemail: "bg-amber-50 text-amber-700",
  no_answer: "bg-slate-100 text-slate-600",
  failed: "bg-red-50 text-red-700",
  pending: "bg-indigo-50 text-indigo-600",
  calling: "bg-purple-50 text-purple-700",
};

export function StatusBadge({ status }: { status: string }) {
  const color = statusColors[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
