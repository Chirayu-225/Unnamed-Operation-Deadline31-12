"use client";

import { FormEvent, useState } from "react";
import { FileTrigger } from "./FileTrigger";

interface Props {
  onSubmit: (formData: FormData) => void;
  loading: boolean;
}

type InstructionMode = "type" | "upload";

export function ScanForm({ onSubmit, loading }: Props) {
  const [primaryFile, setPrimaryFile] = useState<File | null>(null);
  const [relatedFile, setRelatedFile] = useState<File | null>(null);
  const [instruction, setInstruction] = useState("");
  const [instructionMode, setInstructionMode] = useState<InstructionMode>("type");
  const [instructionFile, setInstructionFile] = useState<File | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!primaryFile) return;
    const formData = new FormData();
    formData.append("file", primaryFile);
    if (relatedFile) formData.append("related_files", relatedFile);

    if (instructionMode === "upload" && instructionFile) {
      formData.append("custom_instruction_file", instructionFile);
    } else if (instructionMode === "type" && instruction.trim()) {
      formData.append("custom_instruction", instruction.trim());
    }

    onSubmit(formData);
  }

  function switchMode(next: InstructionMode) {
    setInstructionMode(next);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="card fade-in"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "1rem",
        padding: "1.5rem",
        maxWidth: "560px",
      }}
    >
      <FileTrigger
        id="primary-file"
        label="Table to scan (CSV) *"
        hint="Choose a CSV file"
        file={primaryFile}
        accept=".csv"
        required
        onChange={setPrimaryFile}
      />

      <FileTrigger
        id="related-file"
        label="Related table (optional — enables referential integrity, e.g. accounts.csv for a leads.csv upload)"
        hint="Choose a CSV file"
        file={relatedFile}
        accept=".csv"
        onChange={setRelatedFile}
      />

      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.4rem" }}>
          <label style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
            Custom flagging instruction (optional — plain English)
          </label>
          <div className="toggle-pill" role="tablist" aria-label="Instruction input mode">
            <button
              type="button"
              role="tab"
              aria-selected={instructionMode === "type"}
              className={instructionMode === "type" ? "active" : ""}
              onClick={() => switchMode("type")}
            >
              Type it
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={instructionMode === "upload"}
              className={instructionMode === "upload" ? "active" : ""}
              onClick={() => switchMode("upload")}
            >
              Upload a file
            </button>
          </div>
        </div>

        {instructionMode === "type" ? (
          <textarea
            rows={2}
            placeholder='e.g. "flag any amount greater than 100000" or "flag anything that seems off for this industry"'
            className="input"
            style={{ resize: "vertical" }}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
        ) : (
          <div>
            <FileTrigger
              id="instruction-file"
              label=""
              hint="Choose a .txt or .docx file"
              file={instructionFile}
              accept=".txt,.docx"
              onChange={setInstructionFile}
            />
            <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.35rem" }}>
              Write your instructions in Notepad, Word, or any text editor, save it as a .txt or
              .docx file, and upload it here — the full text becomes the flagging instruction.
            </p>
          </div>
        )}
      </div>

      <button type="submit" className="btn-primary" disabled={!primaryFile || loading} style={{ padding: "0.65rem 1rem", marginTop: "0.25rem" }}>
        {loading ? "Running scan..." : "Run scan"}
      </button>
    </form>
  );
}
