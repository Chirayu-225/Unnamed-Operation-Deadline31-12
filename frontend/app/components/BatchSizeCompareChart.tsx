"use client";

import { DatasetMetrics } from "../eval/data";

/**
 * Before/after comparison: recall at the old guessed default (batch size
 * 20) vs the new empirically-tuned default (batch size 45), per dataset.
 *
 * This is NOT a categorical comparison (different entities) — it's the
 * same measure (recall) at two points of the same config sweep, so per
 * the color-formula it gets a SEQUENTIAL single-hue ramp (light = old,
 * dark = same-hue-darker = new), not two categorical series. Using
 * categorical colors here would wrongly imply "old" and "new" are
 * different entities rather than two levels of one variable.
 */
export function BatchSizeCompareChart({ datasets, newBatchSize }: { datasets: DatasetMetrics[]; newBatchSize: number }) {
  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Dataset</th>
            <th style={thStyle}>Recall @ batch 20</th>
            <th style={thStyle}></th>
            <th style={thStyle}>{`Recall @ batch ${newBatchSize}`}</th>
            <th style={thStyle}>Change</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => {
            const before = d.previousDefault.recall;
            const after = d.fullAgentic.recall;
            const delta = after - before;
            return (
              <tr key={d.name}>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{d.label}</td>
                <td style={tdStyle}>
                  <BarCell value={before} color="var(--ramp-light)" />
                </td>
                <td style={{ ...tdStyle, textAlign: "center", color: "var(--text-muted)" }}>&rarr;</td>
                <td style={tdStyle}>
                  <BarCell value={after} color="var(--ramp-dark)" />
                </td>
                <td
                  style={{
                    ...tdStyle,
                    color: delta >= 0 ? "var(--status-good)" : "var(--status-serious)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {delta >= 0 ? "+" : ""}
                  {(delta * 100).toFixed(1)} pts
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function BarCell({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      <div
        style={{
          flex: 1,
          height: "10px",
          borderRadius: "4px",
          background: "var(--meter-track)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${value * 100}%`,
            height: "100%",
            background: color,
            borderRadius: "4px",
          }}
        />
      </div>
      <span style={{ fontSize: "0.8125rem", fontVariantNumeric: "tabular-nums", minWidth: "3ch" }}>
        {(value * 100).toFixed(1)}
      </span>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  fontSize: "0.75rem",
  color: "var(--text-muted)",
  fontWeight: 500,
  padding: "0.375rem 0.5rem",
  borderBottom: "1px solid var(--gridline)",
};

const tdStyle: React.CSSProperties = {
  padding: "0.5rem",
  borderBottom: "1px solid var(--gridline)",
  fontSize: "0.875rem",
};
