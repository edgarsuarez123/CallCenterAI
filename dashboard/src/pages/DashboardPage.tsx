import { useState, useCallback } from "react";
import { useCampaigns, Campaign } from "../hooks/useCampaigns";
import { useAuth } from "../contexts/AuthContext";
import { useApi } from "../hooks/useApi";
import { CampaignTable } from "../components/campaigns/CampaignTable";
import { StatCard } from "../components/ui/StatCard";
import { Button } from "../components/ui/Button";
import { PageSpinner } from "../components/ui/Spinner";
import { Modal } from "../components/ui/Modal";
import { FileUpload } from "../components/ui/FileUpload";

interface DashboardPageProps {
  onSelectCampaign: (campaign: Campaign) => void;
}

export function DashboardPage({ onSelectCampaign }: DashboardPageProps) {
  const { mode, clinicId } = useAuth();
  const { post, postForm } = useApi();
  const { campaigns, isLoading, error, lastUpdated, refresh } = useCampaigns();
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [showNewModal, setShowNewModal] = useState(false);
  const [newCampaignName, setNewCampaignName] = useState("");
  const [newCampaignReason, setNewCampaignReason] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Stats
  const active = campaigns.filter((c) => c.status === "running" || c.status === "queued").length;
  const totalContacts = campaigns.reduce((sum, c) => sum + c.total_contacts, 0);
  const avgProgress = campaigns.length > 0
    ? Math.round(campaigns.reduce((sum, c) => sum + c.progress_pct, 0) / campaigns.length)
    : 0;

  const handleStart = useCallback(async (campaign: Campaign) => {
    setActionLoading((prev) => ({ ...prev, [campaign.id]: true }));
    try {
      if (mode === "demo") {
        await post(`/admin/clinics/${clinicId}/campaigns/${campaign.id}/start`);
      } else {
        await post(`/campaigns/${campaign.id}/start`);
      }
      await refresh();
    } finally {
      setActionLoading((prev) => ({ ...prev, [campaign.id]: false }));
    }
  }, [mode, clinicId, post, refresh]);

  const handlePause = useCallback(async (campaign: Campaign) => {
    setActionLoading((prev) => ({ ...prev, [campaign.id]: true }));
    try {
      if (mode === "demo") {
        await post(`/admin/clinics/${clinicId}/campaigns/${campaign.id}/pause`);
      } else {
        await post(`/campaigns/${campaign.id}/pause`);
      }
      await refresh();
    } finally {
      setActionLoading((prev) => ({ ...prev, [campaign.id]: false }));
    }
  }, [mode, clinicId, post, refresh]);

  const handleCreateCampaign = async () => {
    if (!newCampaignName.trim()) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      let campaignId: string;

      if (mode === "demo") {
        // Create campaign, then upload CSV if provided
        const res = await post<{ success: boolean; data: { id: string } }>(
          `/admin/clinics/${clinicId}/campaigns`,
          { name: newCampaignName.trim(), reason: newCampaignReason.trim() || "HEDIS care gap outreach" }
        );
        campaignId = res.data.id;

        if (uploadFile) {
          const formData = new FormData();
          formData.append("file", uploadFile);
          await postForm(`/admin/clinics/${clinicId}/campaigns/${campaignId}/upload`, formData);
        }
      } else {
        // JWT mode: single upload call creates the campaign
        if (uploadFile) {
          const formData = new FormData();
          formData.append("file", uploadFile);
          formData.append("name", newCampaignName.trim());
          const res = await postForm<{ campaign_id: string }>(`/campaigns/upload`, formData);
          campaignId = res.campaign_id;
        } else {
          throw new Error("Please upload a CSV to create a campaign.");
        }
      }

      setShowNewModal(false);
      setNewCampaignName("");
      setNewCampaignReason("");
      setUploadFile(null);
      await refresh();
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : "Failed to create campaign");
    } finally {
      setIsCreating(false);
    }
  };

  const secondsAgo = lastUpdated ? Math.round((Date.now() - lastUpdated.getTime()) / 1000) : null;

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Campaigns</h2>
          <p className="text-sm text-slate-500 mt-0.5">Manage outbound HEDIS outreach campaigns</p>
        </div>
        <div className="flex items-center gap-3">
          {secondsAgo !== null && (
            <span className="text-xs text-slate-400">
              Updated {secondsAgo}s ago ·{" "}
              <button onClick={refresh} className="text-indigo-500 hover:text-indigo-700 underline">
                Refresh
              </button>
            </span>
          )}
          <Button onClick={() => setShowNewModal(true)}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Campaign
          </Button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Campaigns" value={campaigns.length} />
        <StatCard label="Active" value={active} color="indigo" />
        <StatCard label="Total Contacts" value={totalContacts.toLocaleString()} />
        <StatCard label="Avg Progress" value={`${avgProgress}%`} color={avgProgress === 100 ? "emerald" : "indigo"} />
      </div>

      {/* Campaign table */}
      {isLoading ? (
        <PageSpinner />
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
      ) : (
        <CampaignTable
          campaigns={campaigns}
          onSelect={onSelectCampaign}
          onStart={handleStart}
          onPause={handlePause}
          actionLoading={actionLoading}
        />
      )}

      {/* New Campaign Modal */}
      {showNewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={() => setShowNewModal(false)} />
          <div className="relative bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-semibold text-slate-900">New Campaign</h3>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Campaign Name *</label>
              <input
                type="text"
                value={newCampaignName}
                onChange={(e) => setNewCampaignName(e.target.value)}
                placeholder="e.g. AWV Outreach Q3 2026"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Reason (optional)</label>
              <input
                type="text"
                value={newCampaignReason}
                onChange={(e) => setNewCampaignReason(e.target.value)}
                placeholder="e.g. Annual wellness visit is overdue"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Patient CSV (optional — upload later)</label>
              <FileUpload
                onUpload={async (f) => setUploadFile(f)}
                label="Drop patient CSV here"
                hint=".csv with patient_name, phone columns"
              />
              {uploadFile && (
                <p className="text-xs text-indigo-600 mt-1">✓ {uploadFile.name} ready to upload</p>
              )}
            </div>

            {createError && <p className="text-xs text-red-600">{createError}</p>}

            <div className="flex gap-3 pt-2">
              <Button variant="secondary" onClick={() => setShowNewModal(false)} className="flex-1" disabled={isCreating}>
                Cancel
              </Button>
              <Button
                onClick={handleCreateCampaign}
                isLoading={isCreating}
                disabled={!newCampaignName.trim()}
                className="flex-1"
              >
                Create Campaign
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
