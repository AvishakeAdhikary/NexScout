"use client";

import { Upload } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

/**
 * Drop files here or click to choose them. Keyboard: Enter or Space opens the file chooser.
 * Files over `maxBytes` or with another extension are refused here, before any upload.
 */
export function FileDropZone({
  label,
  hint,
  accept,
  multiple = false,
  maxBytes,
  disabled = false,
  onFiles,
}: {
  label: string;
  hint?: string;
  accept?: string; // e.g. ".pdf,.docx,.md"
  multiple?: boolean;
  maxBytes?: number;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [over, setOver] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  function accepted(files: File[]): File[] {
    const allowed = accept?.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) ?? [];
    const ok: File[] = [];
    const refused: string[] = [];
    for (const f of files) {
      const ext = f.name.includes(".") ? `.${f.name.split(".").pop()!.toLowerCase()}` : "";
      if (allowed.length && !allowed.includes(ext)) refused.push(`${f.name}: not a supported type`);
      else if (maxBytes && f.size > maxBytes) refused.push(`${f.name}: larger than ${Math.round(maxBytes / 1048576)} MB`);
      else ok.push(f);
    }
    setProblem(refused.length ? refused.join("; ") : null);
    return multiple ? ok : ok.slice(0, 1);
  }

  function take(list: FileList | null) {
    if (!list || disabled) return;
    const files = accepted(Array.from(list));
    if (files.length) onFiles(files);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  }

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      inputRef.current?.click();
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-describedby={hint ? hintId : undefined}
        aria-disabled={disabled}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={onKey}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 py-6 text-center text-sm transition-colors",
          "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          over ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <Upload className="size-5 text-muted-foreground" aria-hidden />
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">Drop {multiple ? "files" : "a file"} here, or click to choose</span>
      </div>
      {hint && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = ""; // choosing the same file again still triggers
        }}
      />
    </div>
  );
}
