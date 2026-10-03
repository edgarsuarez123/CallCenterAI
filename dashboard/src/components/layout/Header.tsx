import { useAuth } from "../../contexts/AuthContext";
import { Button } from "../ui/Button";

interface HeaderProps {
  clinicName?: string;
  title: string;
}

export function Header({ clinicName, title }: HeaderProps) {
  const { user, mode, logout } = useAuth();

  return (
    <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-2">
        <h1 className="text-sm font-semibold text-slate-800">{title}</h1>
        {clinicName && (
          <>
            <span className="text-slate-300">/</span>
            <span className="text-sm text-slate-500">{clinicName}</span>
          </>
        )}
      </div>

      <div className="flex items-center gap-4">
        {mode === "demo" && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-amber-50 border border-amber-200 rounded-full text-xs font-medium text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            Demo Mode
          </span>
        )}
        {user?.email && (
          <span className="text-sm text-slate-500 hidden sm:block">{user.email}</span>
        )}
        <Button variant="ghost" size="sm" onClick={logout}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
