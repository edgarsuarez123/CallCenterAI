import { useState } from "react";
import { Campaign } from "../../hooks/useCampaigns";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

interface CampaignControlsProps {
  campaign: Campaign;
  onAction: (action: "start" | "pause" | "resume" | "cancel" | "process-next") => Promise<void>;
  isLoading: boolean;
  actionResult?: string | null;
}

export function CampaignControls({ campaign, onAction, isLoading, actionResult }: CampaignControlsProps) {
  const [showCancelModal, setShowCancelModal] = useState(false);
  const { status } = campaign;

  const canStart = status === "draft" && campaign.total_contacts > 0;
  const canResume = status === "paused";
  const canPause = status === "running";
  const canCancel = status !== "completed" && status !== "cancelled";
  const canProcessNext = status === "queued" || status === "running";

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {canStart && (
          <Button onClick={() => onAction("start")} isLoading={isLoading}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Start Campaign
          </Button>
        )}
        {status === "draft" && campaign.total_contacts === 0 && (
          <p className="text-sm text-slate-400 italic">Upload a CSV file to start this campaign.</p>
        )}
        {canResume && (
          <Button onClick={() => onAction("resume")} isLoading={isLoading}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            </svg>
            Resume
          </Button>
        )}
        {canPause && (
          <Button variant="secondary" onClick={() => onAction("pause")} isLoading={isLoading}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Pause
          </Button>
        )}
        {canProcessNext && (
          <Button variant="secondary" onClick={() => onAction("process-next")} isLoading={isLoading}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 9l3 3m0 0l-3 3m3-3H8m13 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Simulate Next Call
          </Button>
        )}
        {canCancel && (
          <Button variant="ghost" size="sm" onClick={() => setShowCancelModal(true)} disabled={isLoading}>
            Cancel Campaign
          </Button>
        )}

        {actionResult && (
          <span className="text-sm text-slate-600 bg-slate-100 rounded-lg px-3 py-1.5">
            📞 {actionResult}
          </span>
        )}
      </div>

      {showCancelModal && (
        <Modal
          title="Cancel Campaign"
          description="This will stop all outreach and mark the campaign as cancelled. This cannot be undone."
          confirmLabel="Cancel Campaign"
          confirmVariant="danger"
          isLoading={isLoading}
          onConfirm={async () => {
            await onAction("cancel");
            setShowCancelModal(false);
          }}
          onCancel={() => setShowCancelModal(false)}
        />
      )}
    </>
  );
}
