import { useState } from "react";
import { FileUpload } from "../ui/FileUpload";
import { useAuth } from "../../contexts/AuthContext";
import { useApi } from "../../hooks/useApi";

interface UploadPanelProps {
  campaignId: string;
  onUploaded: () => void;
}

interface UploadResult {
  imported?: number;
  skipped?: number;
  skipped_count?: number;
  total_contacts?: number;
  errors?: string[];
  parse_error_count?: number;
}

export function UploadPanel({ campaignId, onUploaded }: UploadPanelProps) {
  const { mode, clinicId } = useAuth();
  const { postForm } = useApi();
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    setIsLoading(true);
    setResult(null);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      let res: { success?: boolean; data?: UploadResult } & UploadResult;

      if (mode === "demo") {
        res = await postForm(
          `/admin/clinics/${clinicId}/campaigns/${campaignId}/upload`,
          formData
        );
        setResult(res.data ?? res);
      } else {
        // JWT mode: campaigns.py upload also takes campaign_id as form field
        formData.append("campaign_id", campaignId);
        res = await postForm(`/campaigns/upload`, formData);
        setResult(res);
      }
      onUploaded();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setIsLoading(false);
    }
  };

  const imported = result?.imported ?? result?.total_contacts ?? 0;
  const skipped = result?.skipped ?? result?.skipped_count ?? 0;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-800">Upload Patient List</h3>
        <p className="text-xs text-slate-500 mt-0.5">
          CSV must include: <code className="bg-slate-100 px-1 rounded">patient_name</code>,{" "}
          <code className="bg-slate-100 px-1 rounded">phone</code>. Optional:{" "}
          <code className="bg-slate-100 px-1 rounded">gap_type</code>,{" "}
          <code className="bg-slate-100 px-1 rounded">reason</code>.
        </p>
      </div>

      <FileUpload onUpload={handleUpload} isLoading={isLoading} />

      {result && (
        <div className="flex items-start gap-3 p-3 bg-emerald-50 border border-emerald-200 rounded-lg">
          <svg className="h-5 w-5 text-emerald-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="text-sm font-medium text-emerald-800">
              {imported} contact{imported !== 1 ? "s" : ""} imported
            </p>
            {skipped > 0 && (
              <p className="text-xs text-emerald-600 mt-0.5">{skipped} duplicates skipped</p>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-3 p-3 bg-red-50 border border-red-200 rounded-lg">
          <svg className="h-5 w-5 text-red-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}
    </div>
  );
}
