import { METRIC_LABELS, MetricScoreOut, statusForScore } from "../lib/types";

/** Meter form, per the dataviz skill: fill carries severity (status
 * palette by score band), unfilled track is a flat neutral step —
 * state reads across the whole bar, not just the filled portion. */
export function MetricMeter({ metric }: { metric: MetricScoreOut }) {
  const status = statusForScore(metric.score);
  const label = METRIC_LABELS[metric.metric] ?? metric.metric;
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
        aria-valuenow={metric.score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label} score`}
      >
        <div
          style={{
            width: `${Math.max(0, Math.min(100, metric.score))}%`,
            height: "100%",
            background: status.color,
            borderRadius: "5px",
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <span className="tabular" style={{ fontSize: "0.9375rem", color: "var(--text-secondary)", textAlign: "right" }}>
        {metric.score.toFixed(1)}
      </span>
    </div>
  );
}
