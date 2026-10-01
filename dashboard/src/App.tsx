import { useState, useEffect, useCallback } from "react";

// ─── Types ──────────────────────────────────────────────────────────────────

interface Campaign {
  id: string;
  name: string;
  reason: string;
  status: "draft" | "queued" | "running" | "paused" | "completed";
  total_contacts: number;
  completed_contacts: number;
  progress_pct: number;
  created_at: string;
}

interface Contact {
  id: string;
  patient_name: string;
  phone_last4: string;
  reason: string;
  outcome: string;
  call_date: string | null;
  call_duration_seconds: number | null;
  notes: string | null;
}

interface ReportData {
  campaign: Campaign;
  contacts: Contact[];
  summary: Record<string, number>;
}

interface HealthData {
  status: string;
  database: string;
  timestamp: string;
}

// ─── Config ──────────────────────────────────────────────────────────────────

const API_KEY = import.meta.env.VITE_API_KEY || "demo-api-key";
const CLINIC_ID = import.meta.env.VITE_CLINIC_ID || "";

const headers = {
  "X-API-Key": API_KEY,
  "Content-Type": "application/json",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: "bg-gray-100 text-gray-700",
    queued: "bg-yellow-100 text-yellow-800",
    running: "bg-blue-100 text-blue-800",
    paused: "bg-orange-100 text-orange-800",
    completed: "bg-green-100 text-green-800",
    accepted: "bg-green-100 text-green-800",
    declined: "bg-red-100 text-red-800",
    voicemail: "bg-yellow-100 text-yellow-800",
    no_answer: "bg-gray-100 text-gray-700",
    failed: "bg-red-100 text-red-800",
    pending: "bg-blue-100 text-blue-700",
    calling: "bg-purple-100 text-purple-800",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-700"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-12 text-gray-400">
      <div className="text-4xl mb-2">📭</div>
      <p>{message}</p>
    </div>
  );
}

// ─── Campaigns Tab ────────────────────────────────────────────────────────────

function CampaignsTab({
  clinicId,
  onSelectCampaign,
}: {
  clinicId: string;
  onSelectCampaign: (c: Campaign) => void;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clinicId) {
      setError("Set VITE_CLINIC_ID in dashboard/.env.local");
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`/admin/clinics/${clinicId}/campaigns`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setCampaigns(json.data ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [clinicId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Spinner />;
  if (error) return <div className="p-4 bg-red-50 text-red-700 rounded">{error}</div>;
  if (campaigns.length === 0) return <EmptyState message="No campaigns yet. Run seed_demo.py to load demo data." />;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-gray-800">Outreach Campaigns</h2>
        <button onClick={load} className="text-sm text-blue-600 hover:underline">Refresh</button>
      </div>
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
            <tr>
              <th className="text-left px-4 py-3">Campaign Name</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Progress</th>
              <th className="text-left px-4 py-3">Contacts</th>
              <th className="text-left px-4 py-3">Created</th>
              <th className="text-left px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {campaigns.map((c) => (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{c.name}</div>
                  <div className="text-xs text-gray-400 truncate max-w-xs">{c.reason}</div>
                </td>
                <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full"
                        style={{ width: `${c.progress_pct}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500">{c.progress_pct}%</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-600">
                  {c.completed_contacts}/{c.total_contacts}
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => onSelectCampaign(c)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    View Report →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Report Tab ───────────────────────────────────────────────────────────────

function ReportTab({
  clinicId,
  campaign,
  onBack,
}: {
  clinicId: string;
  campaign: Campaign;
  onBack: () => void;
}) {
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/admin/clinics/${clinicId}/campaigns/${campaign.id}/report`,
        { headers }
      );
      const json = await res.json();
      setReport(json.data);
    } finally {
      setLoading(false);
    }
  }, [clinicId, campaign.id]);

  useEffect(() => { load(); }, [load]);

  const processNext = async () => {
    setProcessing(true);
    setLastResult(null);
    try {
      const res = await fetch(
        `/admin/clinics/${clinicId}/campaigns/${campaign.id}/process-next`,
        { method: "POST", headers }
      );
      const json = await res.json();
      if (json.data?.status === "no_pending_contacts") {
        setLastResult("All contacts processed!");
      } else {
        setLastResult(
          `Called ${json.data?.patient_name} → ${json.data?.outcome?.toUpperCase()}`
        );
      }
      await load();
    } finally {
      setProcessing(false);
    }
  };

  if (loading) return <Spinner />;
  if (!report) return <EmptyState message="No report data." />;

  const { summary, contacts } = report;

  return (
    <div>
      <button onClick={onBack} className="text-sm text-blue-600 hover:underline mb-4 block">
        ← Back to campaigns
      </button>
      <h2 className="text-lg font-semibold text-gray-800 mb-1">{campaign.name}</h2>
      <p className="text-sm text-gray-500 mb-4">{campaign.reason}</p>

      {/* Summary cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
        {Object.entries(summary).map(([key, val]) => (
          <div key={key} className="bg-white rounded-lg border border-gray-100 p-3 text-center shadow-sm">
            <div className="text-xl font-bold text-gray-900">{val}</div>
            <div className="text-xs text-gray-500 mt-0.5">{key.replace("_", " ")}</div>
          </div>
        ))}
      </div>

      {/* Demo controls */}
      {campaign.status !== "completed" && (
        <div className="mb-4 flex items-center gap-3">
          <button
            onClick={processNext}
            disabled={processing}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {processing ? "Processing…" : "Process Next Contact (Demo)"}
          </button>
          {lastResult && (
            <span className="text-sm text-gray-600 bg-gray-100 px-3 py-1 rounded">{lastResult}</span>
          )}
        </div>
      )}

      {/* Contacts table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
            <tr>
              <th className="text-left px-4 py-3">Patient</th>
              <th className="text-left px-4 py-3">Phone</th>
              <th className="text-left px-4 py-3">Reason</th>
              <th className="text-left px-4 py-3">Outcome</th>
              <th className="text-left px-4 py-3">Call Date</th>
              <th className="text-left px-4 py-3">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {contacts.map((c) => (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900">{c.patient_name}</td>
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{c.phone_last4}</td>
                <td className="px-4 py-3 text-gray-600 max-w-xs">
                  <span className="truncate block">{c.reason}</span>
                </td>
                <td className="px-4 py-3"><StatusBadge status={c.outcome} /></td>
                <td className="px-4 py-3 text-gray-500">
                  {c.call_date ? new Date(c.call_date).toLocaleDateString() : "—"}
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {c.call_duration_seconds ? `${c.call_duration_seconds}s` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Health Tab ────────────────────────────────────────────────────────────────

function HealthTab() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;
  if (!health) return <EmptyState message="Cannot reach API." />;

  return (
    <div className="max-w-md">
      <h2 className="text-lg font-semibold text-gray-800 mb-4">System Health</h2>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
        <div className="flex justify-between">
          <span className="text-gray-500">API Status</span>
          <StatusBadge status={health.status === "healthy" ? "completed" : "failed"} />
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Database</span>
          <span className="text-sm font-medium text-gray-800">{health.database}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Timestamp</span>
          <span className="text-sm text-gray-600">{new Date(health.timestamp).toLocaleString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Swagger UI</span>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="text-sm text-blue-600 hover:underline"
          >
            localhost:8000/docs →
          </a>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

type Tab = "campaigns" | "report" | "health";

export default function App() {
  const [tab, setTab] = useState<Tab>("campaigns");
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const clinicId = CLINIC_ID;

  const handleSelectCampaign = (c: Campaign) => {
    setSelectedCampaign(c);
    setTab("report");
  };

  const handleBack = () => {
    setSelectedCampaign(null);
    setTab("campaigns");
  };

  const tabs: { key: Tab; label: string }[] = [
    { key: "campaigns", label: "Campaigns" },
    { key: "health", label: "System Health" },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">CallCenterAI</h1>
          <p className="text-xs text-gray-400">HEDIS Outreach Automation Platform</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-green-400 rounded-full" />
          <span className="text-xs text-gray-500">Demo Mode</span>
        </div>
      </header>

      {/* Config warning */}
      {!clinicId && (
        <div className="bg-yellow-50 border-b border-yellow-200 px-6 py-2 text-sm text-yellow-800">
          Set <code className="font-mono">VITE_CLINIC_ID</code> in{" "}
          <code className="font-mono">dashboard/.env.local</code> to connect to your clinic.
          Run <code className="font-mono">python scripts/seed_demo.py</code> to get an ID.
        </div>
      )}

      {/* Tabs */}
      <nav className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-6">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => { setTab(t.key); setSelectedCampaign(null); }}
              className={`py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <main className="px-6 py-6 max-w-6xl mx-auto">
        {(tab === "campaigns") && (
          <CampaignsTab clinicId={clinicId} onSelectCampaign={handleSelectCampaign} />
        )}
        {tab === "report" && selectedCampaign && (
          <ReportTab clinicId={clinicId} campaign={selectedCampaign} onBack={handleBack} />
        )}
        {tab === "health" && <HealthTab />}
      </main>
    </div>
  );
}
