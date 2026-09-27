import { DatasetMetrics } from "../eval/data";

/**
 * Plain-HTML table — the accessibility fallback the dataviz skill
 * requires alongside every chart (screen readers, no-JS, print). Same
 * numbers as GroupedMetricChart / BatchSizeCompareChart, just as a table.
 */
export function MetricsTableView({ datasets }: { datasets: DatasetMetrics[] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
      <caption style={{ textAlign: "left", color: "var(--text-muted)", fontSize: "0.75rem", marginBottom: "0.5rem" }}>
        Full metric table (accessibility fallback for the charts above)
      </caption>
      <thead>
        <tr>
          {["Dataset", "Rows", "Precision", "Recall", "F1", "Semantic-only recall", "Reasoning cycles"].map((h) => (
            <th
              key={h}
              style={{
                textAlign: "left",
                padding: "0.5rem",
                borderBottom: "1px solid var(--gridline)",
                color: "var(--text-muted)",
                fontWeight: 500,
                fontSize: "0.75rem",
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {datasets.map((d) => (
          <tr key={d.name}>
            <td style={{ padding: "0.5rem", borderBottom: "1px solid var(--gridline)" }}>
              <span
                style={{
                  display: "inline-block",
                  width: "8px",
                  height: "8px",
                  borderRadius: "2px",
                  background: d.seriesVar,
                  marginRight: "0.5rem",
                }}
              />
              {d.label}
            </td>
            <td style={tdNum}>{d.totalRows}</td>
            <td style={tdNum}>{d.fullAgentic.precision.toFixed(3)}</td>
            <td style={tdNum}>{d.fullAgentic.recall.toFixed(3)}</td>
            <td style={tdNum}>{d.fullAgentic.f1.toFixed(3)}</td>
            <td style={tdNum}>{d.fullAgentic.semanticOnlyRecall.toFixed(3)}</td>
            <td style={tdNum}>{d.fullAgentic.semanticIterations}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const tdNum: React.CSSProperties = {
  padding: "0.5rem",
  borderBottom: "1px solid var(--gridline)",
  fontVariantNumeric: "tabular-nums",
};
