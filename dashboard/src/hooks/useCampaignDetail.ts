import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useApi } from "./useApi";
import { Campaign } from "./useCampaigns";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Contact {
  id: string;
  patient_name: string;
  phone_last4: string;
  reason: string;
  outcome: string;
  call_date: string | null;
  call_duration_seconds: number | null;
  notes: string | null;
}

export interface OutcomeSummary {
  total: number;
  accepted: number;
  declined: number;
  voicemail: number;
  no_answer: number;
  failed: number;
  pending: number;
  [key: string]: number;
}

export interface CampaignDetail {
  campaign: Campaign;
  contacts: Contact[];
  summary: OutcomeSummary;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useCampaignDetail(campaignId: string, pollingInterval = 30_000) {
  const { mode, clinicId } = useAuth();
  const { get, post } = useApi();
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionResult, setActionResult] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!mode || !campaignId) return;
    try {
      if (mode === "demo") {
        if (!clinicId) return;
        const res = await get<{
          success: boolean;
          data: { campaign: Campaign; contacts: Contact[]; summary: OutcomeSummary };
        }>(`/admin/clinics/${clinicId}/campaigns/${campaignId}/report`);
        setDetail(res.data);
      } else {
        // JWT mode: fetch campaign detail + contacts
        const [campRes, contactsRes] = await Promise.all([
          get<{ campaign: Campaign }>(`/campaigns/${campaignId}`),
          get<{ contacts: Contact[] }>(`/campaigns/${campaignId}/contacts`),
        ]);
        const contacts = contactsRes.contacts ?? [];
        const summary = buildSummary(contacts);
        setDetail({ campaign: campRes.campaign, contacts, summary });
      }
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load campaign");
    } finally {
      setIsLoading(false);
    }
  }, [mode, clinicId, campaignId, get]);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(() => {
      // Stop polling once completed
      if (detail?.campaign.status === "completed" || detail?.campaign.status === "cancelled") {
        if (intervalRef.current) clearInterval(intervalRef.current);
        return;
      }
      load();
    }, pollingInterval);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [load, pollingInterval, detail?.campaign.status]);

  const triggerAction = useCallback(
    async (action: "start" | "pause" | "resume" | "cancel" | "process-next") => {
      if (!mode || !campaignId) return;
      setActionLoading(true);
      setActionResult(null);
      try {
        if (mode === "demo") {
          if (!clinicId) return;
          const path =
            action === "process-next"
              ? `/admin/clinics/${clinicId}/campaigns/${campaignId}/process-next`
              : `/admin/clinics/${clinicId}/campaigns/${campaignId}/${action}`;
          const res = await post<{ success: boolean; data: { contact?: { outcome: string; patient_name?: string }; message?: string } }>(path);
          if (action === "process-next" && res.data?.contact) {
            const outcome = res.data.contact.outcome?.toUpperCase() ?? "PROCESSED";
            const name = res.data.contact.patient_name ?? "Patient";
            setActionResult(`${name} → ${outcome}`);
          }
        } else {
          await post(`/campaigns/${campaignId}/${action}`);
        }
        await load();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setActionLoading(false);
      }
    },
    [mode, clinicId, campaignId, post, load]
  );

  return { detail, isLoading, error, actionLoading, actionResult, triggerAction, refresh: load };
}

function buildSummary(contacts: Contact[]): OutcomeSummary {
  const summary: OutcomeSummary = {
    total: contacts.length,
    accepted: 0,
    declined: 0,
    voicemail: 0,
    no_answer: 0,
    failed: 0,
    pending: 0,
  };
  for (const c of contacts) {
    const outcome = c.outcome?.toLowerCase();
    if (outcome && outcome in summary) {
      summary[outcome]++;
    }
  }
  return summary;
}
