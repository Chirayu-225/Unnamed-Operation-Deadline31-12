export interface MetricScoreOut {
  metric: string;
  score: number;
  flagged_weight: number;
  total_rows: number;
}

export interface FlaggedRowOut {
  row_index: number;
  row_data: Record<string, unknown>;
  deterministic_reasons: string[];
  semantic_reason: string | null;
  semantic_confidence: number | null;
  verification_label: "confirmed" | "needs_review" | "rejected" | null;
  verification_notes: string | null;
  /** A second, independently-derived confidence figure — NOT the raw
   * self-reported number above, which the backend deliberately doesn't
   * trust as a calibrated probability (see service/app/domain/
   * calibration.py). null when there's no semantic flag on this row. */
  calibrated_confidence: number | null;
}

export interface CompilationOut {
  kind: "structured" | "semantic" | "failed";
  description: string;
  error: string | null;
}

export interface ScanResponse {
  table_name: string;
  total_rows: number;
  overall_score: number;
  metric_scores: MetricScoreOut[];
  flagged_rows: FlaggedRowOut[];
  semantic_iterations: number;
  llm_used: boolean;
  compilation: CompilationOut | null;
  warnings: string[];
}

/** A referential-integrity finding that genuinely spans two tables —
 * from_table holds the foreign key, to_table is what it's supposed to
 * reference. Mirrors service/app/main.py's CrossTableFinding. */
export interface CrossTableFinding {
  from_table: string;
  from_column: string;
  to_table: string;
  flagged_row_count: number;
}

/** A CONTENT-level inconsistency between a child row and the parent row
 * its foreign key already resolves to (e.g. a mismatched company name)
 * — as opposed to CrossTableFinding above, which is a structural fact
 * about a foreign key that doesn't resolve at all. Requires an LLM;
 * empty whenever one isn't configured. Mirrors
 * service/app/main.py's CrossTableSemanticFinding. */
export interface CrossTableSemanticFinding {
  from_table: string;
  from_row_index: number;
  to_table: string;
  to_row_index: number;
  fk_column: string;
  reason: string;
  confidence: number;
  verification_label: "confirmed" | "needs_review" | "rejected" | null;
  verification_notes: string | null;
  /** See FlaggedRowOut.calibrated_confidence — same idea, cross-table
   * findings start from a lower base rate (two-hop reasoning). */
  calibrated_confidence: number | null;
}

export interface SchemaScanResponse {
  tables: ScanResponse[];
  cross_table_findings: CrossTableFinding[];
  cross_table_semantic_findings: CrossTableSemanticFinding[];
  aggregate_score: number;
  total_tables: number;
  total_rows: number;
  llm_used: boolean;
  warnings: string[];
}

export const METRIC_LABELS: Record<string, string> = {
  completeness: "Completeness",
  uniqueness: "Uniqueness",
  validity: "Validity",
  consistency: "Consistency",
  accuracy: "Accuracy",
};

/** Status band for a 0-100 score, per the dataviz skill's fixed status
 * palette (good/warning/serious/critical) — never themed, always paired
 * with an icon + label, never color alone. */
export function statusForScore(score: number): {
  band: "good" | "warning" | "serious" | "critical";
  label: string;
  color: string;
} {
  if (score >= 90) return { band: "good", label: "Good", color: "var(--status-good)" };
  if (score >= 70) return { band: "warning", label: "Needs attention", color: "var(--status-warning)" };
  if (score >= 50) return { band: "serious", label: "Serious", color: "var(--status-serious)" };
  return { band: "critical", label: "Critical", color: "var(--status-critical)" };
}
