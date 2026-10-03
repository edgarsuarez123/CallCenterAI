import { useState } from "react";
import { Contact } from "../../hooks/useCampaignDetail";
import { StatusBadge } from "../ui/StatusBadge";

interface ContactsTableProps {
  contacts: Contact[];
}

const OUTCOMES = ["all", "accepted", "declined", "voicemail", "no_answer", "failed", "pending"];
const PAGE_SIZE = 15;

function formatDuration(secs: number | null): string {
  if (!secs) return "—";
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ContactsTable({ contacts }: ContactsTableProps) {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);

  const filtered = filter === "all" ? contacts : contacts.filter((c) => c.outcome === filter);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-3">
      {/* Filter tabs */}
      <div className="flex flex-wrap gap-1.5">
        {OUTCOMES.map((o) => (
          <button
            key={o}
            onClick={() => { setFilter(o); setPage(0); }}
            className={[
              "px-3 py-1 rounded-full text-xs font-medium transition-colors",
              filter === o
                ? "bg-indigo-600 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200",
            ].join(" ")}
          >
            {o === "all" ? `All (${contacts.length})` : `${o.replace(/_/g, " ")} (${contacts.filter((c) => c.outcome === o).length})`}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-sm text-slate-400">
          No contacts match this filter.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Patient</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Phone</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Outcome</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Call Date</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visible.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-5 py-3.5 font-medium text-slate-800">{c.patient_name}</td>
                  <td className="px-5 py-3.5 font-mono text-slate-500 text-xs">***-***-{c.phone_last4}</td>
                  <td className="px-5 py-3.5"><StatusBadge status={c.outcome} /></td>
                  <td className="px-5 py-3.5 text-slate-400 text-xs">
                    {c.call_date ? new Date(c.call_date).toLocaleString() : "—"}
                  </td>
                  <td className="px-5 py-3.5 text-slate-400 text-xs">{formatDuration(c.call_duration_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100 bg-slate-50">
              <span className="text-xs text-slate-400">
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div className="flex gap-1">
                <button
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-200 text-slate-600 disabled:opacity-40 hover:bg-slate-100"
                >
                  ← Prev
                </button>
                <button
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-200 text-slate-600 disabled:opacity-40 hover:bg-slate-100"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
