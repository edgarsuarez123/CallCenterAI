import { ReactNode } from "react";
import { Button } from "./Button";

interface ModalProps {
  title: string;
  description?: string;
  confirmLabel?: string;
  confirmVariant?: "primary" | "danger";
  isLoading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

export function Modal({
  title,
  description,
  confirmLabel = "Confirm",
  confirmVariant = "primary",
  isLoading = false,
  onConfirm,
  onCancel,
  children,
}: ModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md mx-4 p-6">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        {description && <p className="mt-2 text-sm text-slate-500">{description}</p>}
        {children && <div className="mt-4">{children}</div>}
        <div className="mt-6 flex gap-3 justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={isLoading}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={onConfirm} isLoading={isLoading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
