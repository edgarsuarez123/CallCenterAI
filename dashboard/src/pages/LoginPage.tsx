import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";

export function LoginPage() {
  const { loginWithGoogle, loginDemo } = useAuth();
  const [showDemo, setShowDemo] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clinics, setClinics] = useState<{ id: string; name: string }[]>([]);
  const [selectedClinicId, setSelectedClinicId] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<"key" | "clinic">("key");

  const handleKeySubmit = async () => {
    if (!apiKey.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch("/admin/clinics", {
        headers: { "X-API-Key": apiKey.trim(), "Content-Type": "application/json" },
      });
      if (res.status === 401 || res.status === 403) {
        setError("Invalid API key. Please check and try again.");
        return;
      }
      if (!res.ok) throw new Error("Could not reach the API.");
      const data = await res.json();
      const list = (data.data ?? []) as { id: string; name: string }[];
      if (list.length === 0) {
        setError("No clinics found for this API key.");
        return;
      }
      setClinics(list);
      setSelectedClinicId(list[0].id);
      setStep("clinic");
    } catch {
      setError("Cannot reach the API. Is the backend running?");
    } finally {
      setIsLoading(false);
    }
  };

  const handleClinicSelect = () => {
    const clinic = clinics.find((c) => c.id === selectedClinicId);
    if (!clinic) return;
    loginDemo(apiKey.trim(), clinic.id, clinic.name);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-indigo-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center h-14 w-14 bg-indigo-500 rounded-2xl mb-4 shadow-lg">
            <svg className="h-8 w-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white">CallCenterAI</h1>
          <p className="text-slate-400 text-sm mt-1">HEDIS Outreach Platform</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-2xl p-8 space-y-4">
          <h2 className="text-lg font-semibold text-slate-800 text-center">Sign in to your account</h2>

          {/* Google OAuth button */}
          <button
            onClick={loginWithGoogle}
            className="w-full flex items-center justify-center gap-3 border border-slate-200 rounded-xl py-3 px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>

          {/* Divider */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-200" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-white px-3 text-xs text-slate-400">or</span>
            </div>
          </div>

          {/* Demo Login toggle */}
          {!showDemo ? (
            <button
              onClick={() => setShowDemo(true)}
              className="w-full py-2 text-xs text-slate-400 hover:text-slate-600 transition-colors border border-dashed border-slate-200 rounded-xl"
            >
              Demo login (API key)
            </button>
          ) : (
            <div className="border border-dashed border-amber-200 bg-amber-50 rounded-xl p-4 space-y-3">
              <p className="text-xs font-medium text-amber-700">
                Demo Mode — for development and demos only
              </p>

              {step === "key" && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Admin API Key</label>
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleKeySubmit()}
                      placeholder="Enter your admin API key"
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                    />
                  </div>
                  {error && <p className="text-xs text-red-600">{error}</p>}
                  <button
                    onClick={handleKeySubmit}
                    disabled={!apiKey.trim() || isLoading}
                    className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                  >
                    {isLoading ? "Connecting..." : "Continue"}
                  </button>
                </>
              )}

              {step === "clinic" && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">Select Clinic</label>
                    <select
                      value={selectedClinicId}
                      onChange={(e) => setSelectedClinicId(e.target.value)}
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                    >
                      {clinics.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setStep("key")}
                      className="flex-1 border border-slate-200 text-slate-600 text-sm py-2 rounded-lg hover:bg-slate-50"
                    >
                      Back
                    </button>
                    <button
                      onClick={handleClinicSelect}
                      className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                    >
                      Sign in
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
