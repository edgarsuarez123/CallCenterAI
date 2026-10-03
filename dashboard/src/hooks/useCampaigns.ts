import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useApi } from "./useApi";

// ─── Normalized Campaign type ─────────────────────────────────────────────────

export interface Campaign {
  id: string;
  name: string;
  reason: string;
  status: "draft" | "queued" | "running" | "paused" | "completed" | "cancelled";
  total_contacts: number;
  completed_contacts: number;
  progress_pct: number;
  created_at: string;
}

// ─── Raw API shapes ───────────────────────────────────────────────────────────

interface AdminCampaignRaw {
  id: string;
  name: string;
  reason: string;
  status: string;
  total_contacts: number;
  completed_contacts: number;
  progress_pct: number;
  created_at: string;
}

interface StaffCampaignRaw {
  campaign_id: string;
  name: string;
  status: string;
  total_contacts: number;
  called_count: number;
  booked_count: number;
  failed_count: number;
  created_at: string;
}

function normalizeAdmin(c: AdminCampaignRaw): Campaign {
  return {
    id: c.id,
    name: c.name,
    reason: c.reason ?? "",
    status: c.status as Campaign["status"],
    total_contacts: c.total_contacts,
    completed_contacts: c.completed_contacts,
    progress_pct: c.progress_pct ?? (c.total_contacts > 0 ? (c.completed_contacts / c.total_contacts) * 100 : 0),
    created_at: c.created_at,
  };
}

function normalizeStaff(c: StaffCampaignRaw): Campaign {
  const completed = (c.called_count ?? 0) + (c.booked_count ?? 0) + (c.failed_count ?? 0);
  return {
    id: c.campaign_id,
    name: c.name,
    reason: "",
    status: c.status as Campaign["status"],
    total_contacts: c.total_contacts,
    completed_contacts: completed,
    progress_pct: c.total_contacts > 0 ? (completed / c.total_contacts) * 100 : 0,
    created_at: c.created_at,
  };
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useCampaigns(pollingInterval = 30_000) {
  const { mode, clinicId } = useAuth();
  const { get } = useApi();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!mode) return;
    try {
      if (mode === "demo") {
        if (!clinicId) return;
        const res = await get<{ success: boolean; data: AdminCampaignRaw[] }>(
          `/admin/clinics/${clinicId}/campaigns`
        );
        setCampaigns((res.data ?? []).map(normalizeAdmin));
      } else {
        const res = await get<{ campaigns: StaffCampaignRaw[] }>("/campaigns");
        setCampaigns((res.campaigns ?? []).map(normalizeStaff));
      }
      setLastUpdated(new Date());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load campaigns");
    } finally {
      setIsLoading(false);
    }
  }, [mode, clinicId, get]);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, pollingInterval);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [load, pollingInterval]);

  return { campaigns, isLoading, error, lastUpdated, refresh: load };
}
