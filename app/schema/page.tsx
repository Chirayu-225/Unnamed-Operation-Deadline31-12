"use client";

import { useState } from "react";
import { SchemaScanForm } from "../components/SchemaScanForm";
import { ScoreHero } from "../components/ScoreHero";
import { StatTile } from "../components/StatTile";
import { CoverageBadge } from "../components/CoverageBadge";
import { CrossTableFindings } from "../components/CrossTableFindings";
import { CrossTableSemanticFindings } from "../components/CrossTableSemanticFindings";
import { FlaggedRowsTable } from "../components/FlaggedRowsTable";
import { SchemaScanResponse } from "../lib/types";

export default function SchemaScanPage() {
  const [result, setResult] = useState<SchemaScanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  async function handleSubmit(formData: FormData) {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/scan-schema", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.error || `Schema scan failed (HTTP ${res.status})`);
      }
      setResult(data as SchemaScanResponse);
      setExpanded(new Set((data as SchemaScanResponse).tables.map((t) => t.table_name)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function toggleTable(name: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  return (
    <main style={{ maxWidth: "980px", margin: "0 auto", padding: "2.5rem 1.5rem 4rem" }}>
      <header className="fade-in" style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em", margin: 0, color: "var(--text-primary)" }}>
          Schema scan
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "0.375rem", fontSize: "0.9375rem" }}>
          Scan several related tables together — each gets its own quality score, plus a check
          for foreign keys that don&apos;t resolve against any other uploaded table.
        </p>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8125rem", marginTop: "0.625rem", maxWidth: "640px", lineHeight: 1.5 }}>
          Every resolved foreign key also gets a content check — does the child row&apos;s data
          actually look consistent with the parent record it points to (e.g. a contact&apos;s
          company name matching its linked account). An instruction that spans tables by name
          (e.g. &quot;flag leads without a matching account&quot;) still isn&apos;t supported — that
          requires inferring which tables and join key free text is even referring to, a
          separate and much larger problem than judging a pair the system already knows is linked.
        </p>
      </header>

      <SchemaScanForm onSubmit={handleSubmit} loading={loading} />

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

          <ScoreHero score={result.aggregate_score} tableName={`schema (${result.total_tables} tables)`} />

          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <StatTile label="Tables scanned" value={String(result.total_tables)} />
            <StatTile label="Total rows" value={String(result.total_rows)} />
            <StatTile
              label="Cross-table findings"
              value={String(result.cross_table_findings.length)}
              accent={result.cross_table_findings.length > 0 ? "var(--status-warning)" : undefined}
            />
            <StatTile
              label="Content mismatches"
              value={String(result.cross_table_semantic_findings.length)}
              sublabel={result.llm_used ? undefined : "off — no API keys"}
              accent={result.cross_table_semantic_findings.length > 0 ? "var(--status-warning)" : undefined}
            />
          </div>

          <div>
            <CoverageBadge
              ok={result.llm_used}
              label={result.llm_used ? "Semantic reasoning: on" : "Semantic reasoning: off (no API keys)"}
            />
          </div>

          <div className="card" style={{ padding: "1.25rem" }}>
            <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", margin: "0 0 0.75rem" }}>
              Cross-table findings
            </h2>
            <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)", margin: "0 0 0.75rem" }}>
              Foreign keys that don&apos;t resolve against any uploaded table.
            </p>
            <CrossTableFindings findings={result.cross_table_findings} />
          </div>

          <div className="card" style={{ padding: "1.25rem" }}>
            <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", margin: "0 0 0.75rem" }}>
              Cross-table content mismatches
            </h2>
            <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)", margin: "0 0 0.75rem" }}>
              Foreign keys that DO resolve, but whose linked records&apos; content looks
              inconsistent with each other.
            </p>
            <CrossTableSemanticFindings
              findings={result.cross_table_semantic_findings}
              llmUsed={result.llm_used}
            />
          </div>

          <div>
            <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", margin: "0 0 0.875rem" }}>
              Per-table breakdown
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}>
              {result.tables.map((table) => {
                const isOpen = expanded.has(table.table_name);
                return (
                  <div key={table.table_name} className="card" style={{ padding: "1.25rem" }}>
                    <button
                      type="button"
                      onClick={() => toggleTable(table.table_name)}
                      style={{
                        all: "unset",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        width: "100%",
                      }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <span style={{ fontSize: "1rem", fontWeight: 600, color: "var(--text-primary)" }}>
                          {table.table_name}
                        </span>
                        <span className="tabular" style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                          {table.total_rows} rows &middot; {table.flagged_rows.length} flagged
                        </span>
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <span className="tabular" style={{ fontSize: "1.0625rem", fontWeight: 700, color: "var(--text-primary)" }}>
                          {table.overall_score.toFixed(1)}
                        </span>
                        <span style={{ color: "var(--text-muted)", fontSize: "0.8125rem" }}>{isOpen ? "Hide" : "Show"}</span>
                      </span>
                    </button>

                    {isOpen && (
                      <div className="fade-in" style={{ marginTop: "1rem" }}>
                        {table.compilation && (
                          <div
                            style={{
                              padding: "0.75rem 1rem",
                              marginBottom: "1rem",
                              borderRadius: "var(--radius-sm)",
                              background: "var(--surface-2)",
                              fontSize: "0.8125rem",
                            }}
                          >
                            <strong style={{ color: "var(--text-primary)" }}>Instruction understood as:</strong>{" "}
                            <span style={{ color: "var(--text-secondary)" }}>
                              {table.compilation.kind === "failed"
                                ? `Could not compile (${table.compilation.error ?? "unknown error"}).`
                                : `${table.compilation.kind} rule — "${table.compilation.description}"`}
                            </span>
                          </div>
                        )}
                        <FlaggedRowsTable rows={table.flagged_rows} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
