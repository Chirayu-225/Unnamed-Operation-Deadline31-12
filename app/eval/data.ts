/**
 * Eval dashboard data.
 *
 * This is a SNAPSHOT of the last clean, uninterrupted eval run (batch
 * size 45, real Groq + Gemini, all 3 datasets fully covered, zero
 * rate-limit/auth errors) — the numbers copied straight out of
 * `eval_report.md` / `eval_results.json`. It is not a live fetch:
 * `service/eval/run_eval.py` runs against real Groq/Gemini keys and
 * costs real API budget, so this dashboard reads a point-in-time
 * export rather than hitting the harness on every page load.
 *
 * To refresh with a newer run: after `python eval/run_eval.py`
 * completes cleanly (no `error` or `semantic_coverage_warning` on any
 * dataset — a partial run isn't worth graphing), copy the new numbers
 * from `eval_results.json` into EVAL_SNAPSHOT below. `generatedAt` is
 * shown on the page so a viewer always knows how fresh the numbers
 * are, since this file has to be updated by hand.
 */

export interface DatasetMetrics {
  name: string;
  label: string;
  /** CSS var — kept alongside the data so every chart on the page
   * colors this dataset identically (color follows the entity, not
   * its position in whichever chart is drawing it). */
  seriesVar: string;
  totalRows: number;
  plantedIssues: { deterministic: number; semanticOnly: number };
  deterministicBaseline: { precision: number; recall: number; f1: number };
  fullAgentic: {
    precision: number;
    recall: number;
    f1: number;
    semanticOnlyRecall: number;
    semanticIterations: number;
    elapsedSeconds: number;
  };
  /** The size-20 (original guessed default) numbers this session
   * started from, for the before/after batch-size comparison chart. */
  previousDefault: { batchSize: number; recall: number };
}

export const EVAL_SNAPSHOT = {
  generatedAt: "2026-09-25",
  batchSize: 45,
  datasets: [
    {
      name: "crm_leads",
      label: "CRM Leads",
      seriesVar: "var(--series-1)",
      totalRows: 150,
      plantedIssues: { deterministic: 38, semanticOnly: 10 },
      deterministicBaseline: { precision: 1.0, recall: 1.0, f1: 1.0 },
      fullAgentic: {
        precision: 1.0,
        recall: 1.0,
        f1: 1.0,
        semanticOnlyRecall: 1.0,
        semanticIterations: 4,
        elapsedSeconds: null as unknown as number, // not captured in the final clean run's pasted output
      },
      previousDefault: { batchSize: 20, recall: 0.792 },
    },
    {
      name: "ecommerce_orders",
      label: "Ecommerce Orders",
      seriesVar: "var(--series-2)",
      totalRows: 150,
      plantedIssues: { deterministic: 38, semanticOnly: 10 },
      deterministicBaseline: { precision: 1.0, recall: 1.0, f1: 1.0 },
      fullAgentic: {
        precision: 1.0,
        recall: 0.875,
        f1: 0.933,
        semanticOnlyRecall: 0.4,
        semanticIterations: 4,
        elapsedSeconds: null as unknown as number,
      },
      previousDefault: { batchSize: 20, recall: 0.896 },
    },
    {
      name: "hr_employees",
      label: "HR Employees",
      seriesVar: "var(--series-3)",
      totalRows: 143,
      plantedIssues: { deterministic: 31, semanticOnly: 10 },
      deterministicBaseline: { precision: 1.0, recall: 1.0, f1: 1.0 },
      fullAgentic: {
        precision: 1.0,
        recall: 0.878,
        f1: 0.935,
        semanticOnlyRecall: 0.5,
        semanticIterations: 4,
        elapsedSeconds: null as unknown as number,
      },
      previousDefault: { batchSize: 20, recall: 0.756 },
    },
  ] as DatasetMetrics[],
};

export function average(nums: number[]): number {
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}
