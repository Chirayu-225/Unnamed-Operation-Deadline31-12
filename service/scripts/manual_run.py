"""
Manual smoke test: run the CSV connector against two related sample
files (leads.csv referencing accounts.csv via account_id), build a
ScanContext from both, then run all five deterministic checks. This is
meant to be read while you run it, not just executed for a pass/fail.

Run from dbcaas/service:
    PYTHONPATH=. python3 scripts/manual_run.py
"""

from pathlib import Path

from app.agent.generator import GeneratorAgent
from app.canonical.models import ScanContext
from app.checks.completeness import NullCheck
from app.checks.consistency import OutlierCheck
from app.checks.referential_integrity import ReferentialIntegrityCheck
from app.checks.uniqueness import DuplicateCheck
from app.checks.validity import FormatValidityCheck
from app.connectors.base import ConnectorConfig
from app.connectors.csv_connector import CSVConnector
from app.scoring.scorer import compute_scorecard

scripts_dir = Path(__file__).parent


def extract(file_name: str, source_id: str):
    config = ConnectorConfig(
        tenant_id="manual-test",
        source_id=source_id,
        settings={"file_path": str(scripts_dir / file_name)},
    )
    return CSVConnector(config).extract()[0]


leads = extract("sample_leads.csv", "csv-leads")
accounts = extract("accounts.csv", "csv-accounts")
context = ScanContext(tables=[leads, accounts])

print("1. Leads columns:", leads.column_names())
print("2. Rows extracted:", len(leads.rows))
for col in leads.columns:
    print(
        f"   - {col.name}: type={col.type.value}, nullable={col.nullable}, "
        f"hint={col.semantic_hint}"
    )

null_result = NullCheck().run(leads, context)
print("3. Null check flagged rows:", null_result.flagged_row_indices)
print("   detail:", null_result.detail)

dup_result = DuplicateCheck().run(leads, context)
print("4. Duplicate check flagged rows:", dup_result.flagged_row_indices)
print("   detail:", dup_result.detail)

fmt_result = FormatValidityCheck().run(leads, context)
print("5. Format validity flagged rows:", fmt_result.flagged_row_indices)
print("   detail:", fmt_result.detail)

outlier_result = OutlierCheck().run(leads, context)
print("6. Outlier check flagged rows:", outlier_result.flagged_row_indices)
print("   detail:", outlier_result.detail)
print("   (note: account_id is also numeric, so 99 may get flagged here")
print("   too — that's a side effect of it genuinely looking anomalous")
print("   among small sequential IDs, not a bug.)")

ref_result = ReferentialIntegrityCheck().run(leads, context)
print("7. Referential integrity flagged rows (real mode):", ref_result.flagged_row_indices)
print("   detail:", ref_result.detail)

# Demonstrate the fallback mode explicitly — same table, no context.
ref_fallback = ReferentialIntegrityCheck().run(leads, context=None)
print("8. Referential integrity flagged rows (fallback, no context):", ref_fallback.flagged_row_indices)
print("   detail:", ref_fallback.detail)

print()
print("--- Generator agent: same checks, one orchestrated call ---")
agent = GeneratorAgent()
scan_result = agent.run(leads, context)
print("9. Checks the agent planned to run:", [r.check_name for r in scan_result.check_results])
print("10. Union of all flagged rows:", scan_result.flagged_row_indices)
for r in scan_result.check_results:
    print(f"    - {r.check_name}: {r.flagged_row_indices}")

print()
print("--- Scorecard: deterministic checks only (no API keys needed) ---")
scorecard = compute_scorecard(scan_result, leads)
for m in scorecard.metric_scores:
    print(f"11. {m.metric.value}: {m.score}/100  (flagged weight: {m.flagged_weight}/{m.total_rows})")
print(f"12. Overall score: {scorecard.overall_score}/100")
print()
print("    Note: accuracy stays 100 here — that metric only fills in from")
print("    semantic/verified flags, and this run used no LLM at all.")
