import { useState, useEffect, useCallback, useRef } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

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

// ─── Auth storage ─────────────────────────────────────────────────────────────

const STORAGE_KEY_API = "callcenterai_api_key";
const STORAGE_KEY_CLINIC = "callcenterai_clinic_id";

function loadCreds() {
  return {
    apiKey: localStorage.getItem(STORAGE_KEY_API) ?? "",
    clinicId: localStorage.getItem(STORAGE_KEY_CLINIC) ?? "",
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeHeaders(apiKey: string) {
  return { "X-API-Key": apiKey, "Content-Type": "application/json" };
}

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
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-700"}`}
    >
      {status.replace(/_/g, " ")}
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

// ─── Login Screen ─────────────────────────────────────────────────────────────

function LoginScreen({ onLogin }: { onLogin: (apiKey: string, clinicId: string) => void }) {
  const [apiKey, setApiKey] = useState("");
  const [clinicId, setClinicId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim() || !clinicId.trim()) {
      setError("Both fields are required.");
      return;
    }
    setLoading(true);
    setError("");
    // Verify the key works before saving
    try {
      const res = await fetch(`/admin/clinics/${clinicId.trim()}`, {
        headers: { "X-API-Key": apiKey.trim(), "Content-Type": "application/json" },
      });
      if (res.status === 401 || res.status === 403) {
        setError("Invalid API key.");
        return;
      }
      if (res.status === 404) {
        setError("Clinic ID not found.");
        return;
      }
      localStorage.setItem(STORAGE_KEY_API, apiKey.trim());
      localStorage.setItem(STORAGE_KEY_CLINIC, clinicId.trim());
      onLogin(apiKey.trim(), clinicId.trim());
    } catch {
      setError("Cannot reach the API. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">CallCenterAI</h1>
          <p className="text-sm text-gray-500 mt-1">HEDIS Outreach Automation Platform</p>
        </div>
        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 space-y-5"
        >
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Admin API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Your ADMIN_API_KEY"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Clinic ID
            </label>
            <input
              type="text"
              value={clinicId}
              onChange={(e) => setClinicId(e.target.value)}
              placeholder="UUID from seed_demo.py output"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Verifying…" : "Connect"}
          </button>
          <p className="text-xs text-gray-400 text-center">
            Run <code className="font-mono">python scripts/seed_demo.py</code> to get a Clinic ID.
          </p>
        </form>
      </div>
    </div>
  );
}

// ─── Campaigns Tab ────────────────────────────────────────────────────────────

function CampaignsTab({
  clinicId,
  apiKey,
  onSelectCampaign,
}: {
  clinicId: string;
  apiKey: string;
  onSelectCampaign: (c: Campaign) => void;
}) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/admin/clinics/${clinicId}/campaigns`, {
        headers: makeHeaders(apiKey),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setCampaigns(json.data ?? []);
      setLastRefreshed(new Date());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [clinicId, apiKey]);

  // Initial load
  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  const triggerAction = async (campaign: Campaign, action: "start" | "pause") => {
    setActionLoading((prev) => ({ ...prev, [campaign.id]: true }));
    try {
      await fetch(`/admin/clinics/${clinicId}/campaigns/${campaign.id}/${action}`, {
        method: "POST",
        headers: makeHeaders(apiKey),
      });
      await load();
    } finally {
      setActionLoading((prev) => ({ ...prev, [campaign.id]: false }));
    }
  };

  const secondsAgo = Math.round((Date.now() - lastRefreshed.getTime()) / 1000);

  if (loading) return <Spinner />;
  if (error) return <div className="p-4 bg-red-50 text-red-700 rounded">{error}</div>;
  if (campaigns.length === 0)
    return (
      <EmptyState message="No campaigns yet. Run seed_demo.py to load demo data." />
    );

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-gray-800">Outreach Campaigns</h2>
        <div className="flex items-center gap-3 text-sm text-gray-400">
          <span>Updated {secondsAgo}s ago</span>
          <button onClick={load} className="text-blue-600 hover:underline">
            Refresh
          </button>
        </div>
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
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {campaigns.map((c) => (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{c.name}</div>
                  <div className="text-xs text-gray-400 truncate max-w-xs">{c.reason}</div>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={c.status} />
                </td>
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
                  <div className="flex items-center gap-2">
                    {/* Start button — draft, queued, or paused */}
                    {(c.status === "draft" ||
                      c.status === "queued" ||
                      c.status === "paused") && (
                      <button
                        onClick={() => triggerAction(c, "start")}
                        disabled={actionLoading[c.id]}
                        className="text-xs px-2 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                      >
                        {actionLoading[c.id] ? "…" : "Start"}
                      </button>
                    )}
                    {/* Pause button — running only */}
                    {c.status === "running" && (
                      <button
                        onClick={() => triggerAction(c, "pause")}
                        disabled={actionLoading[c.id]}
                        className="text-xs px-2 py-1 bg-orange-500 text-white rounded hover:bg-orange-600 disabled:opacity-50"
                      >
                        {actionLoading[c.id] ? "…" : "Pause"}
                      </button>
                    )}
                    <button
                      onClick={() => onSelectCampaign(c)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Report →
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── CSV Upload ────────────────────────────────────────────────────────────────

function CsvUpload({
  clinicId,
  campaignId,
  apiKey,
  onUploaded,
}: {
  clinicId: string;
  campaignId: string;
  apiKey: string;
  onUploaded: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `/admin/clinics/${clinicId}/campaigns/${campaignId}/upload`,
        { method: "POST", headers: { "X-API-Key": apiKey }, body: form }
      );
      const json = await res.json();
      if (res.ok) {
        const added = json.data?.contacts_added ?? json.data?.added ?? "?";
        setResult({ ok: true, message: `${added} contacts uploaded.` });
        if (fileRef.current) fileRef.current.value = "";
        onUploaded();
      } else {
        setResult({ ok: false, message: json.detail ?? `Upload failed (${res.status}).` });
      }
    } catch {
      setResult({ ok: false, message: "Network error during upload." });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mb-5 p-4 bg-gray-50 rounded-lg border border-gray-200">
      <p className="text-sm font-medium text-gray-700 mb-2">Upload Patient CSV</p>
      <div className="flex items-center gap-3">
        <input
          ref={fileRef}
          type="file"
          accept=".csv"
          className="text-sm text-gray-600 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
        />
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>
      {result && (
        <p
          className={`mt-2 text-xs ${result.ok ? "text-green-700" : "text-red-600"}`}
        >
          {result.ok ? "✓" : "✗"} {result.message}
        </p>
      )}
    </div>
  );
}

// ─── Report Tab ───────────────────────────────────────────────────────────────

function ReportTab({
  clinicId,
  apiKey,
  campaign,
  onBack,
}: {
  clinicId: string;
  apiKey: string;
  campaign: Campaign;
  onBack: () => void;
}) {
  const [report, setReport] = useState<ReportData | null>(null);
  const [currentCampaign, setCurrentCampaign] = useState<Campaign>(campaign);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/admin/clinics/${clinicId}/campaigns/${campaign.id}/report`,
        { headers: makeHeaders(apiKey) }
      );
      const json = await res.json();
      setReport(json.data);
      if (json.data?.campaign) setCurrentCampaign(json.data.campaign);
    } finally {
      setLoading(false);
    }
  }, [clinicId, campaign.id, apiKey]);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh every 30 seconds while campaign is active
  useEffect(() => {
    if (currentCampaign.status === "completed") return;
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load, currentCampaign.status]);

  const processNext = async () => {
    setProcessing(true);
    setLastResult(null);
    try {
      const res = await fetch(
        `/admin/clinics/${clinicId}/campaigns/${campaign.id}/process-next`,
        { method: "POST", headers: makeHeaders(apiKey) }
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
  const isDraft = currentCampaign.status === "draft";

  return (
    <div>
      <button onClick={onBack} className="text-sm text-blue-600 hover:underline mb-4 block">
        ← Back to campaigns
      </button>
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold text-gray-800">{currentCampaign.name}</h2>
        <StatusBadge status={currentCampaign.status} />
      </div>
      <p className="text-sm text-gray-500 mb-5">{currentCampaign.reason}</p>

      {/* CSV upload — only shown for draft campaigns with no contacts yet */}
      {isDraft && (
        <CsvUpload
          clinicId={clinicId}
          campaignId={campaign.id}
          apiKey={apiKey}
          onUploaded={load}
        />
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
        {Object.entries(summary).map(([key, val]) => (
          <div
            key={key}
            className="bg-white rounded-lg border border-gray-100 p-3 text-center shadow-sm"
          >
            <div className="text-xl font-bold text-gray-900">{val}</div>
            <div className="text-xs text-gray-500 mt-0.5">{key.replace(/_/g, " ")}</div>
          </div>
        ))}
      </div>

      {/* Demo controls */}
      {currentCampaign.status !== "completed" && currentCampaign.status !== "draft" && (
        <div className="mb-4 flex items-center gap-3">
          <button
            onClick={processNext}
            disabled={processing}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {processing ? "Processing…" : "Process Next Contact (Demo)"}
          </button>
          {lastResult && (
            <span className="text-sm text-gray-600 bg-gray-100 px-3 py-1 rounded">
              {lastResult}
            </span>
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
            {contacts.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-8 text-gray-400 text-xs">
                  No contacts yet. Upload a CSV to get started.
                </td>
              </tr>
            ) : (
              contacts.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{c.patient_name}</td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                    {c.phone_last4}
                  </td>
                  <td className="px-4 py-3 text-gray-600 max-w-xs">
                    <span className="truncate block">{c.reason}</span>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.outcome} />
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {c.call_date ? new Date(c.call_date).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {c.call_duration_seconds ? `${c.call_duration_seconds}s` : "—"}
                  </td>
                </tr>
              ))
            )}
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
          <span className="text-sm text-gray-600">
            {new Date(health.timestamp).toLocaleString()}
          </span>
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

type Tab = "campaigns" | "health";

export default function App() {
  const [creds, setCreds] = useState(loadCreds);
  const [tab, setTab] = useState<Tab>("campaigns");
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);

  const isLoggedIn = Boolean(creds.apiKey && creds.clinicId);

  const handleLogin = (apiKey: string, clinicId: string) => {
    setCreds({ apiKey, clinicId });
  };

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_KEY_API);
    localStorage.removeItem(STORAGE_KEY_CLINIC);
    setCreds({ apiKey: "", clinicId: "" });
    setSelectedCampaign(null);
    setTab("campaigns");
  };

  if (!isLoggedIn) {
    return <LoginScreen onLogin={handleLogin} />;
  }

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
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-green-400 rounded-full" />
            <span className="text-xs text-gray-500">Demo Mode</span>
          </div>
          <button
            onClick={handleLogout}
            className="text-xs text-gray-400 hover:text-gray-700 border border-gray-200 rounded px-2 py-1"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Tabs */}
      <nav className="bg-white border-b border-gray-200 px-6">
        <div className="flex gap-6">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => {
                setTab(t.key);
                setSelectedCampaign(null);
              }}
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
        {tab === "campaigns" && !selectedCampaign && (
          <CampaignsTab
            clinicId={creds.clinicId}
            apiKey={creds.apiKey}
            onSelectCampaign={(c) => setSelectedCampaign(c)}
          />
        )}
        {tab === "campaigns" && selectedCampaign && (
          <ReportTab
            clinicId={creds.clinicId}
            apiKey={creds.apiKey}
            campaign={selectedCampaign}
            onBack={() => setSelectedCampaign(null)}
          />
        )}
        {tab === "health" && <HealthTab />}
      </main>
    </div>
  );
}
