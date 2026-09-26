"""
Live full scorecard demo — the complete pipeline: deterministic checks
+ semantic reasoning + verification + scoring, all together. Real
Groq and Gemini API calls.

Run from dbcaas/service, with GROQ_API_KEY and GEMINI_API_KEY set:
    PYTHONPATH=. python3 scripts/full_scorecard_demo.py
"""

from app.agent.generator import GeneratorAgent
from app.agent.llm_clients import GeminiClient, GroqClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.scoring.scorer import compute_scorecard

table = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="accounts",
    columns=[
        ColumnSchema(name="company", type=ColumnType.STRING, nullable=False),
        ColumnSchema(name="industry", type=ColumnType.STRING),
        ColumnSchema(name="email", type=ColumnType.STRING, nullable=False, semantic_hint="email"),
    ],
    rows=[
        {"company": "Acme Software Inc", "industry": "Technology", "email": "info@acme.com"},
        {"company": "Globex Data Systems", "industry": "Technology", "email": "hello@globex.com"},
        {"company": "Joe's Bakery", "industry": "Technology", "email": "not-an-email"},
        {"company": "Initech Cloud Solutions", "industry": "Technology", "email": "contact@initech.com"},
    ],
)

print("Running full pipeline: deterministic checks + semantic reasoning + verifier + scoring...")
print()

try:
    agent = GeneratorAgent()
    result = agent.run(table, llm=GroqClient(), verifier_llm=GeminiClient())

    print("Deterministic check results:")
    for r in result.check_results:
        print(f"  - {r.check_name} ({r.metric.value}): {r.flagged_row_indices}")

    print()
    print("Semantic flags (Groq):", [(f.row_index, f.reason) for f in result.semantic_flags])
    print("Verified (Gemini):", [(v.row_index, v.label.value) for v in result.verified_flags])

    print()
    scorecard = compute_scorecard(result, table)
    for m in scorecard.metric_scores:
        print(f"  {m.metric.value}: {m.score}/100")
    print(f"Overall score: {scorecard.overall_score}/100")
    print()
    print("Expect accuracy < 100 here — row 2 (the bakery) should have been")
    print("flagged and confirmed, unlike the deterministic-only demo.")

except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)
