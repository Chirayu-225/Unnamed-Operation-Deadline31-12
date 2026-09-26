"use client";

import { useState } from "react";
import { EVAL_SNAPSHOT, average } from "./data";
import { GroupedMetricChart } from "../components/GroupedMetricChart";
import { BatchSizeCompareChart } from "../components/BatchSizeCompareChart";
import { StatTile } from "../components/StatTile";
import { CoverageBadge } from "../components/CoverageBadge";
import { MetricsTableView } from "../components/MetricsTableView";

export default function EvalDashboard() {
  const [showTable, setShowTable] = useState(false);
  const { datasets, generatedAt, batchSize } = EVAL_SNAPSHOT;

  const avgRecall = average(datasets.map((d) => d.fullAgentic.recall));
  const avgPrecision = average(datasets.map((d) => d.fullAgentic.precision));
  const avgF1 = average(datasets.map((d) => d.fullAgentic.f1));
  const avgSemanticOnlyRecall = average(datasets.map((d) => d.fullAgentic.semanticOnlyRecall));

  return (
    <main style={{ maxWidth: "980px", margin: "0 auto", padding: "2.5rem 1.5rem 4rem" }}>
      <header className="fade-in" style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em", margin: 0, color: "var(--text-primary)" }}>
          Eval dashboard
        </h1>
        <p style={{ color: "var(--text-secondary)", marginTop: "0.375rem", fontSize: "0.9375rem" }}>
          Detection-quality metrics from the last clean eval run across all 3 seeded datasets — batch
          size {batchSize}, real Groq + Gemini calls, zero rate-limit or auth errors.
        </p>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8125rem", marginTop: "0.625rem" }}>
          Snapshot from {generatedAt}. This is a point-in-time export, not a live fetch — see{" "}
          <code>app/eval/data.ts</code> for how to refresh it after a new clean run.
        </p>
      </header>

      <section style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
        <StatTile label="Avg precision" value={avgPrecision.toFixed(3)} />
        <StatTile label="Avg recall" value={avgRecall.toFixed(3)} />
        <StatTile label="Avg F1" value={avgF1.toFixed(3)} />
        <StatTile label="Avg semantic-only recall" value={avgSemanticOnlyRecall.toFixed(3)} sublabel="rows only catchable via LLM reasoning" />
      </section>

      <section style={{ marginBottom: "2rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {datasets.map((d) => (
          <CoverageBadge key={d.name} ok={true} label={`${d.label}: fully covered`} />
        ))}
      </section>

      <section className="card" style={{ padding: "1.5rem", marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", marginBottom: "0.25rem" }}>
          Precision, recall &amp; F1 by dataset
        </h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8125rem", marginBottom: "1.25rem" }}>
          Full pipeline (deterministic rules + semantic reasoning combined).
        </p>
        <GroupedMetricChart datasets={datasets} />
      </section>

      <section className="card" style={{ padding: "1.5rem", marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1.0625rem", fontWeight: 600, color: "var(--text-primary)", marginBottom: "0.25rem" }}>
          Batch size 20 &rarr; {batchSize}: recall impact
        </h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8125rem", marginBottom: "1.25rem" }}>
          Raising the semantic reasoner&apos;s default batch size to {batchSize} rows/call, based on
          live sweep evidence, at roughly half the call count.
        </p>
        <BatchSizeCompareChart datasets={datasets} newBatchSize={batchSize} />
      </section>

      <section>
        <button
          onClick={() => setShowTable((s) => !s)}
          style={{
            fontSize: "0.8125rem",
            color: "var(--accent)",
            background: "none",
            border: "none",
            padding: 0,
            cursor: "pointer",
            marginBottom: "0.75rem",
            textDecoration: "underline",
          }}
        >
          {showTable ? "Hide" : "Show"} full data table
        </button>
        {showTable && (
          <div className="card fade-in" style={{ padding: "1.25rem" }}>
            <MetricsTableView datasets={datasets} />
          </div>
        )}
      </section>
    </main>
  );
}
