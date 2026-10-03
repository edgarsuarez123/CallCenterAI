import { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useAuth } from "../../contexts/AuthContext";

type View = "dashboard" | "settings";

interface LayoutProps {
  children: ReactNode;
  currentView: View;
  onNavigate: (view: View) => void;
  title: string;
}

export function Layout({ children, currentView, onNavigate, title }: LayoutProps) {
  const { user } = useAuth();
  const clinicName = user?.clinicName || undefined;

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Sidebar currentView={currentView} onNavigate={onNavigate} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header title={title} clinicName={clinicName} />
        <main className="flex-1 overflow-y-auto px-6 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
