import { Campaign } from "../hooks/useCampaigns";
import { useCampaignDetail } from "../hooks/useCampaignDetail";
import { CampaignControls } from "../components/campaigns/CampaignControls";
import { CampaignStats } from "../components/campaigns/CampaignStats";
import { ContactsTable } from "../components/campaigns/ContactsTable";
import { UploadPanel } from "../components/campaigns/UploadPanel";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ProgressBar } from "../components/ui/ProgressBar";
import { PageSpinner } from "../components/ui/Spinner";

interface CampaignDetailPageProps {
  campaign: Campaign;
  onBack: () => void;
}

export function CampaignDetailPage({ campaign, onBack }: CampaignDetailPageProps) {
  const { detail, isLoading, error, actionLoading, actionResult, triggerAction, refresh } =
    useCampaignDetail(campaign.id);

  const c = detail?.campaign ?? campaign;

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Campaigns
        </button>
        <span className="text-slate-300">/</span>
        <span className="text-sm font-medium text-slate-800">{c.name}</span>
      </div>

      {/* Campaign header */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-xl font-semibold text-slate-900">{c.name}</h2>
              <StatusBadge status={c.status} />
            </div>
            {c.reason && <p className="text-sm text-slate-500">{c.reason}</p>}
            <p className="text-xs text-slate-400 mt-1">
              Created {new Date(c.created_at).toLocaleDateString()} ·{" "}
              {c.total_contacts} contact{c.total_contacts !== 1 ? "s" : ""}
            </p>
          </div>
          <button
            onClick={refresh}
            className="text-xs text-indigo-500 hover:text-indigo-700 underline"
          >
            Refresh
          </button>
        </div>

        {/* Progress bar */}
        {c.total_contacts > 0 && (
          <div className="mt-4">
            <div className="flex justify-between text-xs text-slate-500 mb-1.5">
              <span>{c.completed_contacts} completed</span>
              <span>{c.total_contacts} total</span>
            </div>
            <ProgressBar pct={c.progress_pct} height="lg" showLabel />
          </div>
        )}

        {/* Controls */}
        <div className="mt-4 pt-4 border-t border-slate-100">
          <CampaignControls
            campaign={c}
            onAction={triggerAction}
            isLoading={actionLoading}
            actionResult={actionResult}
          />
        </div>
      </div>

      {isLoading && !detail && <PageSpinner />}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
      )}

      {/* Upload panel (draft only) */}
      {c.status === "draft" && (
        <UploadPanel campaignId={c.id} onUploaded={refresh} />
      )}

      {/* Stats */}
      {detail && (
        <section>
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Outcome Summary</h3>
          <CampaignStats summary={detail.summary} totalContacts={c.total_contacts} />
        </section>
      )}

      {/* Contacts */}
      {detail && detail.contacts.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-700 mb-3">
            Contacts ({detail.contacts.length})
          </h3>
          <ContactsTable contacts={detail.contacts} />
        </section>
      )}
    </div>
  );
}
