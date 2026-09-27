/** Status is never color-alone — always icon + label, using the
 * reserved status palette (never a series color). */
export function CoverageBadge({ ok, label }: { ok: boolean; label: string }) {
  const color = ok ? "var(--status-good)" : "var(--status-warning)";
  const icon = ok ? "✓" : "⚠";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.375rem",
        padding: "0.3rem 0.7rem",
        borderRadius: "var(--radius-full)",
        background: "var(--surface-2)",
        border: `1px solid ${color}`,
        color,
        fontSize: "0.75rem",
        fontWeight: 600,
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <span aria-hidden="true">{icon}</span>
      <span style={{ color: "var(--text-secondary)", fontWeight: 500 }}>{label}</span>
    </span>
  );
}
