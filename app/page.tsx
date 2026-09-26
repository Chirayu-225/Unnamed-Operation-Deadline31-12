"use client";

import { useState } from "react";
import { ScanForm } from "./components/ScanForm";
import { ScoreHero } from "./components/ScoreHero";
import { MetricMeter } from "./components/MetricMeter";
import { FlaggedRowsTable } from "./components/FlaggedRowsTable";
import { StatTile } from "./components/StatTile";
import { CoverageBadge } from "./components/CoverageBadge";
import { ScanResponse } from "./lib/types";

export default function Home() {
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(formData: FormData) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/scan", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.error || `Scan failed (HTTP ${res.status})`);
      }
      setResult(data as ScanResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: "980px", margin: "0 auto", padding: "2.5rem 1.5rem 4rem" }}>
      <header className="fade-in" style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em", margin: 0, color: "var(--text-primary)" }}>
          DBCaaS
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "0.375rem", fontSize: "0.9375rem" }}>
          Schema-agnostic data connectivity with agentic data quality scoring — test dashboard.
        </p>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8125rem", marginTop: "0.625rem", maxWidth: "640px", lineHeight: 1.5 }}>
          Stateless for now — no login, no saved history, nothing persists between scans. That
          part of the roadmap (DB, auth, multi-tenancy) is deliberately on hold while this pass
          focuses on evaluating the detection pipeline itself.
        </p>
      </header>

      <ScanForm onSubmit={handleSubmit} loading={loading} />

      {error && (
        <div
          role="alert"
          className="fade-in"
          style={{
            marginTop: "1.25rem",
            padding: "0.75rem 1rem",
            borderRadius: "var(--radius-sm)",
            background: "var(--surface-1)",
            border: "1px solid var(--status-critical)",
            color: "var(--text-primary)",
            fontSize: "0.9375rem",
          }}
        >
          {error}
        </div>
      )}

      {result && (
        <section style={{ marginTop: "2.5rem", display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          {result.warnings.length > 0 && (
            <div
              className="fade-in"
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface-1)",
                border: "1px solid var(--status-warning)",
                fontSize: "0.875rem",
                color: "var(--text-secondary)",
              }}
            >
              {result.warnings.map((w, i) => (
                <div key={i}>{w}</div>
              ))}
            </div>
          )}

          <ScoreHero score={result.overall_score} tableName={result.table_name} />

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <StatTile label="Rows scanned" value={String(result.total_rows)} />
            <StatTile
              label="Flagged"
              value={String(result.flagged_rows.length)}
              sublabel={
                result.total_rows > 0
                  ? `${((result.flagged_rows.length / result.total_rows) * 100).toFixed(1)}% of rows`
                  : undefined
              }
              accent={result.flagged_rows.length > 0 ? "var(--status-warning)" : undefined}
            />
            <StatTile
              label="Reasoning cycles"
              value={result.llm_used ? String(result.semantic_iterations) : "—"}
              sublabel={result.llm_used ? "semantic passes run" : undefined}
            />
          </div>

          <div>
            <CoverageBadge
              ok={result.llm_used}
              label={result.llm_used ? "Semantic reasoning: on" : "Semantic reasoning: off (no API keys)"}
            />
          </div>

          {result.compilation && (
            <div className="card" style={{ padding: "1rem 1.25rem", fontSize: "0.875rem" }}>
              <strong style={{ color: "var(--text-primary)" }}>Custom instruction understood as:</strong>{" "}
              <span style={{ color: "var(--text-secondary)" }}>
                {result.compilation.kind === "failed"
                  ? `Could not compile this instruction (${result.compilation.error ?? "unknown error"}).`
                  : `${result.compilation.kind} rule — "${result.compilation.description}"`}
              </span>
            </div>
          )}

          <div className="card" style={{ padding: "1.25rem" }}>
            <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", margin: "0 0 0.75rem" }}>
              Metric breakdown
            </h2>
            {result.metric_scores.map((m) => (
              <MetricMeter key={m.metric} metric={m} />
            ))}
          </div>

          <div className="card" style={{ padding: "1.25rem" }}>
            <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", margin: "0 0 0.75rem" }}>
              Flagged rows
            </h2>
            <FlaggedRowsTable rows={result.flagged_rows} />
          </div>
        </section>
      )}
    </main>
  );
}
