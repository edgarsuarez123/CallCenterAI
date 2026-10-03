import { useState, useEffect } from "react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../contexts/AuthContext";
import { Button } from "../components/ui/Button";
import { PageSpinner } from "../components/ui/Spinner";

interface ClinicSettings {
  timezone: string;
  calling_hours_start: string;
  calling_hours_end: string;
  campaign_concurrency_limit: number;
  max_attempts: number;
  voicemail_retry_hours: number;
  no_answer_retry_hours: number;
  error_retry_hours: number;
}

export function SettingsPage() {
  const { mode, user } = useAuth();
  const { get, patch } = useApi();
  const [settings, setSettings] = useState<ClinicSettings | null>(null);
  const [draft, setDraft] = useState<ClinicSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = user?.role === "admin";

  useEffect(() => {
    const load = async () => {
      try {
        if (mode === "demo") {
          // Demo mode: settings not available via this endpoint
          setSettings(null);
          setIsLoading(false);
          return;
        }
        const res = await get<ClinicSettings>("/clinic/settings");
        setSettings(res);
        setDraft(res);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load settings");
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, [mode, get]);

  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    setError(null);
    try {
      const res = await patch<ClinicSettings>("/clinic/settings", draft);
      setSettings(res);
      setDraft(res);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setIsSaving(false);
    }
  };

  const update = (key: keyof ClinicSettings, value: string | number) => {
    if (!draft) return;
    setDraft({ ...draft, [key]: value });
  };

  if (isLoading) return <PageSpinner />;

  if (mode === "demo") {
    return (
      <div className="max-w-2xl">
        <h2 className="text-xl font-semibold text-slate-900 mb-1">Settings</h2>
        <p className="text-sm text-slate-500 mb-6">Clinic operational settings</p>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-700">
          <strong>Demo Mode:</strong> Clinic settings require Google OAuth authentication. Sign in with Google to manage settings.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Settings</h2>
        <p className="text-sm text-slate-500 mt-0.5">Clinic operational settings</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
      )}

      {draft && (
        <div className="space-y-4">
          {/* Calling Hours */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">Calling Hours</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Start Time</label>
                <input
                  type="time"
                  value={draft.calling_hours_start}
                  onChange={(e) => update("calling_hours_start", e.target.value)}
                  disabled={!isAdmin}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">End Time</label>
                <input
                  type="time"
                  value={draft.calling_hours_end}
                  onChange={(e) => update("calling_hours_end", e.target.value)}
                  disabled={!isAdmin}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>
          </div>

          {/* Concurrency */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">Campaign Settings</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Concurrent Calls</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={draft.campaign_concurrency_limit}
                  onChange={(e) => update("campaign_concurrency_limit", parseInt(e.target.value))}
                  disabled={!isAdmin}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Max Attempts</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={draft.max_attempts}
                  onChange={(e) => update("max_attempts", parseInt(e.target.value))}
                  disabled={!isAdmin}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>
          </div>

          {/* Retry hours */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
            <h3 className="text-sm font-semibold text-slate-800">Retry Configuration</h3>
            <div className="grid grid-cols-3 gap-4">
              {[
                { key: "voicemail_retry_hours", label: "Voicemail retry (hrs)" },
                { key: "no_answer_retry_hours", label: "No answer retry (hrs)" },
                { key: "error_retry_hours", label: "Error retry (hrs)" },
              ].map(({ key, label }) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
                  <input
                    type="number"
                    min={1}
                    value={draft[key as keyof ClinicSettings] as number}
                    onChange={(e) => update(key as keyof ClinicSettings, parseInt(e.target.value))}
                    disabled={!isAdmin}
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              ))}
            </div>
          </div>

          {isAdmin && (
            <div className="flex items-center gap-3">
              <Button onClick={handleSave} isLoading={isSaving}>
                Save Settings
              </Button>
              {saved && <span className="text-sm text-emerald-600">✓ Saved</span>}
              <Button
                variant="secondary"
                onClick={() => setDraft(settings)}
                disabled={isSaving}
              >
                Reset
              </Button>
            </div>
          )}
          {!isAdmin && (
            <p className="text-xs text-slate-400">You have viewer access — contact an admin to change settings.</p>
          )}
        </div>
      )}
    </div>
  );
}
