import { METRIC_LABELS, MetricScoreOut, statusForScore } from "../lib/types";

/** Meter form, per the dataviz skill: fill carries severity (status
 * palette by score band), unfilled track is a flat neutral step —
 * state reads across the whole bar, not just the filled portion. */
export function MetricMeter({ metric }: { metric: MetricScoreOut }) {
  const label = METRIC_LABELS[metric.metric] ?? metric.metric;

  // Not evaluated (no applicable check ran) — an empty/neutral track,
  // never a score, and never rendered as if it were a clean 100. See
  // service/app/scoring/scorer.py's module docstring for the bug this
  // distinction fixes.
  if (!metric.evaluated || metric.score === null) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr 64px", alignItems: "center", gap: "0.75rem", padding: "0.5rem 0" }}>
        <span style={{ fontSize: "0.9375rem", color: "var(--text-primary)" }}>{label}</span>
        <div
          style={{
            height: "10px",
            borderRadius: "5px",
            background: "var(--meter-track)",
            overflow: "hidden",
          }}
          role="meter"
          aria-label={`${label} score — not evaluated`}
        />
        <span className="tabular" style={{ fontSize: "0.9375rem", color: "var(--text-secondary)", textAlign: "right" }}>
          N/A
        </span>
      </div>
    );
  }

  const score = metric.score;
  const status = statusForScore(score);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "140px 1fr 64px", alignItems: "center", gap: "0.75rem", padding: "0.5rem 0" }}>
      <span style={{ fontSize: "0.9375rem", color: "var(--text-primary)" }}>{label}</span>
      <div
        style={{
          height: "10px",
          borderRadius: "5px",
          background: "var(--meter-track)",
          overflow: "hidden",
        }}
        role="meter"
        aria-valuenow={score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} score`}
      >
        <div
          style={{
            width: `${Math.max(0, Math.min(100, score))}%`,
            height: "100%",
            background: status.color,
            borderRadius: "5px",
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <span className="tabular" style={{ fontSize: "0.9375rem", color: "var(--text-secondary)", textAlign: "right" }}>
        {score.toFixed(1)}
      </span>
    </div>
  );
}
