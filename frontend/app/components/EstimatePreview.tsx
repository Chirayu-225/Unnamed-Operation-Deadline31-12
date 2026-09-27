import { ScanEstimateResponse } from "../lib/types";

export type PreflightState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; estimate: ScanEstimateResponse }
  | { status: "error"; message: string };

/** Compact preflight summary shown inside ScanForm, between the file
 * pickers and the submit button — deliberately NOT a row of StatTile
 * cards (that's the right form for a scan's RESULT, where four numbers
 * are the main content of the screen; here they're a secondary,
 * before-you-commit preview inside an already-dense form, so a single
 * inline line reusing the same subdued panel treatment as the
 * "Instruction understood as" panel elsewhere in this app is the less
 * cluttering choice). Renders nothing at all in the idle state — no
 * placeholder box reserving space before there's anything to say. */
export function EstimatePreview({ state }: { state: PreflightState }) {
  if (state.status === "idle") return null;

  if (state.status === "loading") {
    return (
      <p
        className="fade-in"
        style={{ fontSize: "0.8125rem", color: "var(--text-muted)", margin: 0 }}
      >
        Estimating scan cost…
      </p>
    );
  }

  if (state.status === "error") {
    // Deliberately low visual weight, no status color — this is a
    // failure of a secondary preview, never a reason to alarm the user
    // or suggest the scan itself can't run.
    return (
      <p
        className="fade-in"
        style={{ fontSize: "0.8125rem", color: "var(--text-muted)", margin: 0, fontStyle: "italic" }}
      >
        Couldn&apos;t estimate cost — you can still run the scan.
      </p>
    );
  }

  const { estimate } = state;
  const totalRows = estimate.tables.reduce((sum, t) => sum + t.total_rows, 0);
  const coveragePct =
    estimate.tables.length > 0
      ? estimate.tables.reduce((sum, t) => sum + t.estimated_coverage_pct, 0) / estimate.tables.length
      : 100;

  return (
    <div
      className="fade-in"
      style={{
        padding: "0.65rem 0.9rem",
        borderRadius: "var(--radius-sm)",
        background: "var(--surface-2)",
        fontSize: "0.8125rem",
      }}
    >
      {estimate.llm_configured ? (
        <span className="tabular" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{totalRows}</strong> rows &middot;{" "}
          <strong style={{ color: "var(--text-primary)" }}>{estimate.total_estimated_llm_calls}</strong>{" "}
          {estimate.total_estimated_llm_calls === 1 ? "LLM call" : "LLM calls"} &middot;{" "}
          <strong style={{ color: "var(--text-primary)" }}>{coveragePct.toFixed(0)}%</strong> coverage
          &middot; ~
          <strong style={{ color: "var(--text-primary)" }}>${estimate.total_estimated_cost_usd.toFixed(4)}</strong>
          <span style={{ color: "var(--text-muted)" }}> (illustrative)</span>
        </span>
      ) : (
        <span style={{ color: "var(--text-muted)" }}>
          <span className="tabular">{totalRows}</span> rows &middot; no API keys configured — this
          scan will run deterministic checks only, 0 LLM calls.
        </span>
      )}
    </div>
  );
}
