"use client";

import { useRef } from "react";

/** Shared styled file-upload trigger — a hidden native input plus a
 * themed label standing in for it, since a plain <input type=file>
 * can't be styled directly. Used by both ScanForm (single-table) and
 * SchemaScanForm (multi-table), so both read identically. */
export function FileTrigger({
  id,
  label,
  hint,
  file,
  accept,
  required,
  onChange,
}: {
  id: string;
  label?: string;
  hint?: string;
  file: File | null;
  accept: string;
  required?: boolean;
  onChange: (f: File | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div>
      {label && (
        <label htmlFor={id} style={{ display: "block", fontSize: "0.8125rem", color: "var(--text-muted)", marginBottom: "0.3rem" }}>
          {label}
        </label>
      )}
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        required={required}
        style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none" }}
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      <button
        type="button"
        className={`file-btn${file ? " has-file" : ""}`}
        onClick={() => inputRef.current?.click()}
      >
        <span aria-hidden="true">{file ? "✓" : "⬆"}</span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {file ? file.name : hint ?? "Choose a file"}
        </span>
      </button>
    </div>
  );
}
