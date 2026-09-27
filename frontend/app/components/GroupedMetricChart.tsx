"use client";

import { useState } from "react";
import { DatasetMetrics } from "../eval/data";

type MetricKey = "precision" | "recall" | "f1";

const METRICS: { key: MetricKey; label: string }[] = [
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
  { key: "f1", label: "F1" },
];

/**
 * Grouped bar chart: one group per metric (precision/recall/F1), one
 * bar per dataset within each group — magnitude comparison across a
 * fixed small set of entities, the textbook grouped-bar job. Dataset
 * color is fixed (series-1/2/3) and identical to every other chart on
 * the page, per "color follows the entity, never its rank."
 *
 * Hand-built SVG, no charting library — thin bars, 4px rounded data
 * ends, 2px gaps, a legend (3 series, all direct-labeled), and a hover
 * tooltip, per the dataviz skill's mark spec.
 */
export function GroupedMetricChart({ datasets }: { datasets: DatasetMetrics[] }) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);

  const width = 640;
  const height = 260;
  const padding = { top: 16, right: 16, bottom: 36, left: 36 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const groupW = plotW / METRICS.length;
  const barGap = 3;
  const barW = (groupW - barGap * (datasets.length + 1)) / datasets.length;

  const yFor = (v: number) => padding.top + plotH * (1 - v);

  return (
    <div style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", overflow: "visible" }}
        role="img"
        aria-label="Precision, recall and F1 by dataset"
      >
        {/* recessive gridlines at 0, 0.25, 0.5, 0.75, 1.0 */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yFor(t)}
              y2={yFor(t)}
              stroke="var(--gridline)"
              strokeWidth={1}
            />
            <text x={padding.left - 8} y={yFor(t)} textAnchor="end" dominantBaseline="middle" fontSize={10} fill="var(--text-muted)">
              {t.toFixed(2)}
            </text>
          </g>
        ))}

        {METRICS.map((metric, gi) => {
          const groupX = padding.left + gi * groupW;
          return (
            <g key={metric.key}>
              <text
                x={groupX + groupW / 2}
                y={height - padding.bottom + 18}
                textAnchor="middle"
                fontSize={12}
                fill="var(--text-secondary)"
              >
                {metric.label}
              </text>
              {datasets.map((d, di) => {
                const value = d.fullAgentic[metric.key];
                const barX = groupX + barGap + di * (barW + barGap);
                const barH = plotH * value;
                const barY = yFor(value);
                return (
                  <g key={d.name}>
                    <rect
                      x={barX}
                      y={barY}
                      width={barW}
                      height={barH}
                      rx={4}
                      ry={4}
                      fill={d.seriesVar}
                      style={{ cursor: "pointer" }}
                      onMouseEnter={(e) =>
                        setHover({
                          x: barX + barW / 2,
                          y: barY,
                          text: `${d.label} · ${metric.label}: ${value.toFixed(3)}`,
                        })
                      }
                      onMouseLeave={() => setHover(null)}
                    />
                    {/* direct label — 3 series is within the "<=4 direct-labeled" allowance */}
                    <text
                      x={barX + barW / 2}
                      y={barY - 4}
                      textAnchor="middle"
                      fontSize={9}
                      fill="var(--text-secondary)"
                      className="tabular"
                    >
                      {value.toFixed(2)}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {hover && (
        <div
          style={{
            position: "absolute",
            left: `${(hover.x / width) * 100}%`,
            top: `${(hover.y / height) * 100}%`,
            transform: "translate(-50%, -110%)",
            background: "var(--surface-1)",
            border: "1px solid var(--gridline)",
            borderRadius: "6px",
            padding: "0.25rem 0.5rem",
            fontSize: "0.75rem",
            color: "var(--text-primary)",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
          }}
        >
          {hover.text}
        </div>
      )}

      <Legend datasets={datasets} />
    </div>
  );
}

export function Legend({ datasets }: { datasets: DatasetMetrics[] }) {
  return (
    <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", marginTop: "0.75rem", justifyContent: "center" }}>
      {datasets.map((d) => (
        <div key={d.name} style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
          <span
            style={{
              width: "10px",
              height: "10px",
              borderRadius: "3px",
              background: d.seriesVar,
              display: "inline-block",
            }}
          />
          <span style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>{d.label}</span>
        </div>
      ))}
    </div>
  );
}
