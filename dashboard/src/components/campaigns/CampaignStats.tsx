import { OutcomeSummary } from "../../hooks/useCampaignDetail";
import { StatCard } from "../ui/StatCard";

interface CampaignStatsProps {
  summary: OutcomeSummary;
  totalContacts: number;
}

export function CampaignStats({ summary, totalContacts }: CampaignStatsProps) {
  const pct = totalContacts > 0 ? Math.round(((summary.total - (summary.pending ?? 0)) / totalContacts) * 100) : 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      <StatCard label="Total" value={totalContacts} />
      <StatCard label="Accepted" value={summary.accepted ?? 0} color="emerald" />
      <StatCard label="Declined" value={summary.declined ?? 0} color="red" />
      <StatCard label="Voicemail" value={summary.voicemail ?? 0} color="amber" />
      <StatCard label="No Answer" value={summary.no_answer ?? 0} color="slate" />
      <StatCard label="Pending" value={summary.pending ?? 0} sub={`${pct}% complete`} color="indigo" />
    </div>
  );
}
