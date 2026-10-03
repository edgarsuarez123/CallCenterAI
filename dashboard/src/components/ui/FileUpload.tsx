import { useState, useRef, DragEvent, ChangeEvent } from "react";
import { Button } from "./Button";

interface FileUploadProps {
  accept?: string;
  onUpload: (file: File) => Promise<void>;
  isLoading?: boolean;
  label?: string;
  hint?: string;
}

export function FileUpload({
  accept = ".csv,.xlsx",
  onUpload,
  isLoading = false,
  label = "Upload CSV or Excel",
  hint = "Drag and drop or click to select. Max 10MB.",
}: FileUploadProps) {
  const [dragging, setDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  };

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setSelectedFile(file);
  };

  const handleSubmit = async () => {
    if (!selectedFile) return;
    await onUpload(selectedFile);
    setSelectedFile(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={[
          "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
          dragging
            ? "border-indigo-400 bg-indigo-50"
            : selectedFile
            ? "border-indigo-300 bg-indigo-50/50"
            : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50",
        ].join(" ")}
      >
        <div className="flex flex-col items-center gap-2">
          <svg className={`h-10 w-10 ${selectedFile ? "text-indigo-500" : "text-slate-300"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {selectedFile ? (
            <>
              <p className="text-sm font-medium text-indigo-700">{selectedFile.name}</p>
              <p className="text-xs text-slate-400">{(selectedFile.size / 1024).toFixed(1)} KB — click to change</p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-slate-600">{label}</p>
              <p className="text-xs text-slate-400">{hint}</p>
            </>
          )}
        </div>
        <input ref={inputRef} type="file" accept={accept} onChange={handleChange} className="hidden" />
      </div>

      {selectedFile && (
        <Button onClick={handleSubmit} isLoading={isLoading} disabled={isLoading} className="w-full">
          Upload {selectedFile.name}
        </Button>
      )}
    </div>
  );
}
