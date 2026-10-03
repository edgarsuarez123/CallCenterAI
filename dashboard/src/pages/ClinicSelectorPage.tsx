import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { PageSpinner } from "../components/ui/Spinner";

interface ClinicMembership {
  clinic_id: string;
  clinic_name: string;
  role: string;
}

export function ClinicSelectorPage() {
  const { token, selectClinic, logout } = useAuth();
  const [clinics, setClinics] = useState<ClinicMembership[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch("/auth/me", {
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        });
        const data = await res.json();
        setClinics(data.clinics ?? []);
      } catch {
        setError("Failed to load clinics. Please try again.");
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, [token]);

  const handleSelect = async (clinic: ClinicMembership) => {
    setSelecting(clinic.clinic_id);
    try {
      const res = await fetch("/auth/select-clinic", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ clinic_id: clinic.clinic_id }),
      });
      const data = await res.json();
      selectClinic(data.token, clinic.clinic_id, clinic.clinic_name, clinic.role);
    } catch {
      setError("Failed to select clinic. Please try again.");
    } finally {
      setSelecting(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-2xl shadow-xl border border-slate-200 p-8">
          <h2 className="text-lg font-semibold text-slate-800 mb-1">Select a Clinic</h2>
          <p className="text-sm text-slate-500 mb-6">
            Your account has access to multiple clinics. Choose one to continue.
          </p>

          {isLoading && <PageSpinner />}
          {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

          <div className="space-y-2">
            {clinics.map((clinic) => (
              <button
                key={clinic.clinic_id}
                onClick={() => handleSelect(clinic)}
                disabled={!!selecting}
                className="w-full text-left border border-slate-200 rounded-xl p-4 hover:border-indigo-300 hover:bg-indigo-50/50 transition-colors disabled:opacity-60"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-800">{clinic.clinic_name}</p>
                    <p className="text-xs text-slate-400 mt-0.5 capitalize">{clinic.role}</p>
                  </div>
                  {selecting === clinic.clinic_id ? (
                    <svg className="animate-spin h-4 w-4 text-indigo-600" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  )}
                </div>
              </button>
            ))}
          </div>

          <button
            onClick={logout}
            className="mt-6 w-full text-center text-xs text-slate-400 hover:text-slate-600 transition-colors"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
