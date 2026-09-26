import { CrossTableSemanticFinding } from "../lib/types";

function VerificationBadge({ label }: { label: CrossTableSemanticFinding["verification_label"] }) {
  if (!label) return null;
  const spec =
    label === "confirmed"
      ? { color: "var(--status-critical)", text: "Confirmed" }
      : label === "needs_review"
        ? { color: "var(--status-warning)", text: "Needs review" }
        : { color: "var(--status-good)", text: "Rejected on review" };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", fontSize: "0.75rem" }}>
      <svg width="7" height="7" viewBox="0 0 8 8" aria-hidden="true">
        <circle cx="4" cy="4" r="4" fill={spec.color} />
      </svg>
      <span style={{ color: "var(--text-muted)" }}>{spec.text}</span>
    </span>
  );
}

/** Content-level cross-table findings — a child row whose data doesn't
 * actually match the parent row its (already-valid) foreign key points
 * to. Distinct from CrossTableFindings.tsx, which lists FKs that don't
 * resolve at all; this only ever concerns pairs that DID resolve. */
export function CrossTableSemanticFindings({
  findings,
  llmUsed,
}: {
  findings: CrossTableSemanticFinding[];
  llmUsed: boolean;
}) {
  if (!llmUsed) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
        Off — needs semantic reasoning, which needs server API keys (see the coverage badge above).
      </p>
    );
  }

  if (findings.length === 0) {
    return (
      <p style={{ color: "var(--text-secondary)", fontSize: "0.9375rem" }}>
        No content mismatches found between linked records — every resolved foreign-key pair
        looked consistent.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.625rem" }}>
      {findings.map((f, i) => (
        <div
          key={i}
          style={{
            padding: "0.75rem 0.875rem",
            borderRadius: "var(--radius-sm)",
            background: "var(--surface-2)",
            border: "1px solid var(--gridline)",
            fontSize: "0.875rem",
          }}
        >
          <div style={{ color: "var(--text-primary)", marginBottom: "0.3rem" }}>
            <code>{f.from_table}</code> row {f.from_row_index} &harr; <code>{f.to_table}</code> row{" "}
            {f.to_row_index}
            <span className="tabular" style={{ color: "var(--text-muted)", marginLeft: "0.4rem" }}>
              via {f.fk_column}
            </span>
          </div>
          <div style={{ color: "var(--text-secondary)" }}>
            {f.reason}
            <span className="tabular" style={{ color: "var(--text-muted)" }}>
              {" "}
              (confidence {f.confidence.toFixed(2)})
            </span>
          </div>
          <div style={{ marginTop: "0.3rem" }}>
            <VerificationBadge label={f.verification_label} />
          </div>
        </div>
      ))}
    </div>
  );
}
