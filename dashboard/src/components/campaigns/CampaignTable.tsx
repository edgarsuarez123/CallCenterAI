import { Campaign } from "../../hooks/useCampaigns";
import { StatusBadge } from "../ui/StatusBadge";
import { ProgressBar } from "../ui/ProgressBar";
import { Button } from "../ui/Button";

interface CampaignTableProps {
  campaigns: Campaign[];
  onSelect: (campaign: Campaign) => void;
  onStart: (campaign: Campaign) => Promise<void>;
  onPause: (campaign: Campaign) => Promise<void>;
  actionLoading: Record<string, boolean>;
}

export function CampaignTable({
  campaigns,
  onSelect,
  onStart,
  onPause,
  actionLoading,
}: CampaignTableProps) {
  if (campaigns.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-12 text-center">
        <svg className="h-10 w-10 text-slate-300 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
          />
        </svg>
        <p className="text-sm font-medium text-slate-600">No campaigns yet</p>
        <p className="text-xs text-slate-400 mt-1">Upload a patient CSV to create your first campaign.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200">
            <th className="px-5 py-3.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Campaign</th>
            <th className="px-5 py-3.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Status</th>
            <th className="px-5 py-3.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wider w-40">Progress</th>
            <th className="px-5 py-3.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Contacts</th>
            <th className="px-5 py-3.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wider">Created</th>
            <th className="px-5 py-3.5 text-right text-xs font-medium text-slate-500 uppercase tracking-wider">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {campaigns.map((c) => (
            <tr
              key={c.id}
              onClick={() => onSelect(c)}
              className="hover:bg-slate-50 cursor-pointer transition-colors"
            >
              <td className="px-5 py-4">
                <p className="font-medium text-slate-900">{c.name}</p>
                {c.reason && <p className="text-xs text-slate-400 mt-0.5 truncate max-w-xs">{c.reason}</p>}
              </td>
              <td className="px-5 py-4">
                <StatusBadge status={c.status} />
              </td>
              <td className="px-5 py-4 w-40">
                <ProgressBar pct={c.progress_pct} showLabel />
              </td>
              <td className="px-5 py-4 text-slate-600">
                {c.completed_contacts}/{c.total_contacts}
              </td>
              <td className="px-5 py-4 text-slate-400 text-xs">
                {new Date(c.created_at).toLocaleDateString()}
              </td>
              <td className="px-5 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                <div className="flex gap-2 justify-end">
                  {(c.status === "draft" || c.status === "queued" || c.status === "paused") && (
                    <Button
                      size="sm"
                      variant="primary"
                      isLoading={actionLoading[c.id]}
                      onClick={() => onStart(c)}
                    >
                      {c.status === "paused" ? "Resume" : "Start"}
                    </Button>
                  )}
                  {c.status === "running" && (
                    <Button
                      size="sm"
                      variant="secondary"
                      isLoading={actionLoading[c.id]}
                      onClick={() => onPause(c)}
                    >
                      Pause
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => onSelect(c)}>
                    View →
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
