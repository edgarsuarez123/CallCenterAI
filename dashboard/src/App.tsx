import { useEffect, useState } from "react";
import { useAuth } from "./contexts/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { ClinicSelectorPage } from "./pages/ClinicSelectorPage";
import { DashboardPage } from "./pages/DashboardPage";
import { CampaignDetailPage } from "./pages/CampaignDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { Layout } from "./components/layout/Layout";
import { Campaign } from "./hooks/useCampaigns";

type View = "dashboard" | "settings";

export default function App() {
  const { isAuthenticated, isClinicSelected, tokenType, handleOAuthCallback } = useAuth();
  const [view, setView] = useState<View>("dashboard");
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);

  // Handle Google OAuth callback — parse token from URL hash
  useEffect(() => {
    if (window.location.pathname === "/auth/callback" || window.location.hash.includes("token=")) {
      handleOAuthCallback();
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [handleOAuthCallback]);

  // Not authenticated → login
  if (!isAuthenticated) {
    return <LoginPage />;
  }

  // Google JWT unscoped (multi-clinic) → clinic selector
  if (tokenType === "unscoped" && !isClinicSelected) {
    return <ClinicSelectorPage />;
  }

  const title =
    selectedCampaign && view === "dashboard"
      ? selectedCampaign.name
      : view === "settings"
      ? "Settings"
      : "Campaigns";

  return (
    <Layout
      currentView={selectedCampaign ? "dashboard" : view}
      onNavigate={(v) => {
        setView(v);
        setSelectedCampaign(null);
      }}
      title={title}
    >
      {selectedCampaign ? (
        <CampaignDetailPage
          campaign={selectedCampaign}
          onBack={() => setSelectedCampaign(null)}
        />
      ) : view === "settings" ? (
        <SettingsPage />
      ) : (
        <DashboardPage onSelectCampaign={setSelectedCampaign} />
      )}
    </Layout>
  );
}
