import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type AuthMode = "google" | "demo" | null;

interface UserInfo {
  email: string;
  clinicName: string;
  role: string;
}

interface AuthState {
  mode: AuthMode;
  isAuthenticated: boolean;
  isClinicSelected: boolean;
  token: string | null;          // Google JWT
  tokenType: "scoped" | "unscoped" | null;
  apiKey: string | null;         // Demo mode
  clinicId: string | null;       // Demo mode (also scoped JWT)
  user: UserInfo | null;
}

interface AuthContextValue extends AuthState {
  isLoading: boolean;
  loginWithGoogle: () => void;
  handleOAuthCallback: () => boolean;
  loginDemo: (apiKey: string, clinicId: string, clinicName: string) => void;
  selectClinic: (token: string, clinicId: string, clinicName: string, role: string) => void;
  logout: () => void;
}

// ─── Storage keys ─────────────────────────────────────────────────────────────

const STORAGE_PREFIX = "ccai_";
const K = {
  mode: `${STORAGE_PREFIX}mode`,
  token: `${STORAGE_PREFIX}token`,
  tokenType: `${STORAGE_PREFIX}token_type`,
  apiKey: `${STORAGE_PREFIX}api_key`,
  clinicId: `${STORAGE_PREFIX}clinic_id`,
  userEmail: `${STORAGE_PREFIX}user_email`,
  clinicName: `${STORAGE_PREFIX}clinic_name`,
  role: `${STORAGE_PREFIX}role`,
};

function loadFromStorage(): AuthState {
  const mode = (localStorage.getItem(K.mode) as AuthMode) || null;
  const token = localStorage.getItem(K.token);
  const tokenType = (localStorage.getItem(K.tokenType) as "scoped" | "unscoped") || null;
  const apiKey = localStorage.getItem(K.apiKey);
  const clinicId = localStorage.getItem(K.clinicId);
  const email = localStorage.getItem(K.userEmail);
  const clinicName = localStorage.getItem(K.clinicName);
  const role = localStorage.getItem(K.role);

  const user = email ? { email, clinicName: clinicName ?? "", role: role ?? "viewer" } : null;

  const isAuthenticated =
    (mode === "google" && !!token) || (mode === "demo" && !!apiKey && !!clinicId);

  const isClinicSelected =
    mode === "demo"
      ? !!clinicId
      : mode === "google"
      ? tokenType === "scoped"
      : false;

  return { mode, isAuthenticated, isClinicSelected, token, tokenType, apiKey, clinicId, user };
}

function clearStorage() {
  Object.values(K).forEach((k) => localStorage.removeItem(k));
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(loadFromStorage);
  const [isLoading, setIsLoading] = useState(false);

  // Re-sync from storage on mount (handles page refresh mid-login)
  useEffect(() => {
    setState(loadFromStorage());
  }, []);

  const loginWithGoogle = useCallback(() => {
    window.location.href = "/auth/google";
  }, []);

  /**
   * Call this on the /auth/callback page.
   * Parses the token from the URL hash fragment set by the backend.
   * Returns true if a token was found and stored.
   */
  const handleOAuthCallback = useCallback((): boolean => {
    const hash = window.location.hash.slice(1);
    if (!hash) return false;

    const params = new URLSearchParams(hash);
    const token = params.get("token");
    const tokenType = params.get("type") as "scoped" | "unscoped" | null;

    if (!token || !tokenType) return false;

    // Decode JWT payload to get email/clinicId
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      const email = payload.email ?? "";
      const clinicId = payload.clinic_id ?? null;
      const role = payload.role ?? "viewer";

      localStorage.setItem(K.mode, "google");
      localStorage.setItem(K.token, token);
      localStorage.setItem(K.tokenType, tokenType);
      if (email) localStorage.setItem(K.userEmail, email);
      if (clinicId) localStorage.setItem(K.clinicId, clinicId);
      if (role) localStorage.setItem(K.role, role);

      setState(loadFromStorage());
      return true;
    } catch {
      return false;
    }
  }, []);

  const loginDemo = useCallback((apiKey: string, clinicId: string, clinicName: string) => {
    localStorage.setItem(K.mode, "demo");
    localStorage.setItem(K.apiKey, apiKey);
    localStorage.setItem(K.clinicId, clinicId);
    localStorage.setItem(K.clinicName, clinicName);
    localStorage.setItem(K.role, "admin");
    setState(loadFromStorage());
  }, []);

  const selectClinic = useCallback(
    (token: string, clinicId: string, clinicName: string, role: string) => {
      localStorage.setItem(K.token, token);
      localStorage.setItem(K.tokenType, "scoped");
      localStorage.setItem(K.clinicId, clinicId);
      localStorage.setItem(K.clinicName, clinicName);
      localStorage.setItem(K.role, role);
      setState(loadFromStorage());
    },
    []
  );

  const logout = useCallback(() => {
    clearStorage();
    setState({
      mode: null,
      isAuthenticated: false,
      isClinicSelected: false,
      token: null,
      tokenType: null,
      apiKey: null,
      clinicId: null,
      user: null,
    });
  }, []);

  const value: AuthContextValue = {
    ...state,
    isLoading,
    loginWithGoogle,
    handleOAuthCallback,
    loginDemo,
    selectClinic,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
