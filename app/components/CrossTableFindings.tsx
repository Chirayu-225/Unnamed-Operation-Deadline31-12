import { CrossTableFinding } from "../lib/types";

/** Lists genuine cross-table referential-integrity findings — rows in
 * one table whose foreign key doesn't resolve against another uploaded
 * table. Status icon + label per the dataviz skill's rule that status
 * is never color-alone. */
export function CrossTableFindings({ findings }: { findings: CrossTableFinding[] }) {
  if (findings.length === 0) {
    return (
      <p style={{ color: "var(--text-secondary)", fontSize: "0.9375rem" }}>
        No cross-table issues found — every foreign-key-shaped column that had a matching
        table resolved cleanly.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.625rem" }}>
      {findings.map((f, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.625rem",
            padding: "0.75rem 0.875rem",
            borderRadius: "var(--radius-sm)",
            background: "var(--surface-2)",
            border: "1px solid var(--status-warning)",
            fontSize: "0.875rem",
          }}
        >
          <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true" style={{ flexShrink: 0 }}>
            <circle cx="4" cy="4" r="4" fill="var(--status-warning)" />
          </svg>
          <span style={{ color: "var(--text-primary)" }}>
            <code>{f.from_table}</code>.<code>{f.from_column}</code> &rarr; <code>{f.to_table}</code>
          </span>
          <span className="tabular" style={{ color: "var(--text-muted)", marginLeft: "auto" }}>
            {f.flagged_row_count} row{f.flagged_row_count === 1 ? "" : "s"} don&apos;t resolve
          </span>
        </div>
      ))}
    </div>
  );
}
