"""
Live end-to-end demo — the full generator -> verifier pipeline, with
REAL Groq and Gemini API calls. This is the first script that
exercises both providers together in the actual pipeline shape, not
just individually.

Dataset has several genuine semantic issues (bakeries/diners/salons
mislabeled as "Technology") scattered through a larger table, plus
normal rows that should NOT get flagged — a reasonable outcome is the
generator flagging the mismatched rows and the verifier confirming
them, with everything else left alone. LLM output isn't perfectly
deterministic, so exact wording and the exact iteration count may
vary run to run.

The table is deliberately larger than the semantic sample size (20
rows) and deliberately dense with mismatches in the first stretch of
rows, so there's a realistic chance the iteration loop
(GeneratorAgent._run_semantic_with_iteration, see README) actually
fires a second cycle on unseen rows when the first sample comes back
over the 20% flag-ratio threshold — watch `semantic_iterations` in
the output below. A single cycle is still a perfectly normal
outcome; this is a live LLM call, not a guaranteed trigger.

Run from dbcaas/service, with both GROQ_API_KEY and GEMINI_API_KEY set:
    PYTHONPATH=. python3 scripts/full_pipeline_demo.py
"""

from app.agent.generator import GeneratorAgent
from app.agent.llm_clients import GeminiClient, GroqClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType

# First 20 rows (one full sample batch) are dense with mismatches, to
# give the iteration loop a real chance to trigger a second cycle on
# rows 20+ when this first batch comes back over the 20% threshold.
_mismatched = [
    {"company": "Joe's Bakery", "industry": "Technology"},
    {"company": "Sunrise Diner", "industry": "Technology"},
    {"company": "Glow Nail Salon", "industry": "Technology"},
    {"company": "Corner Barbershop", "industry": "Technology"},
    {"company": "Fresh Leaf Florist", "industry": "Technology"},
    {"company": "Riverside Laundromat", "industry": "Technology"},
]
_normal = [
    {"company": "Acme Software Inc", "industry": "Technology"},
    {"company": "Globex Data Systems", "industry": "Technology"},
    {"company": "Initech Cloud Solutions", "industry": "Technology"},
    {"company": "Northwind Analytics", "industry": "Technology"},
]

table = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="accounts",
    columns=[
        ColumnSchema(name="company", type=ColumnType.STRING),
        ColumnSchema(name="industry", type=ColumnType.STRING),
    ],
    # 6 mismatches + 14 normal rows in the first 20 (one sample batch,
    # >20% flag ratio expected), then 10 more clean rows available for
    # a possible second cycle.
    rows=(_mismatched + _normal * 4)[:20] + _normal * 3,
)

print("Running full generator -> verifier pipeline (real Groq + real Gemini)...")
print()

try:
    agent = GeneratorAgent()
    result = agent.run(table, llm=GroqClient(), verifier_llm=GeminiClient())

    print(f"Generator (Groq) proposed {len(result.semantic_flags)} semantic flag(s):")
    for f in result.semantic_flags:
        print(f"  - row {f.row_index}: {f.reason} (confidence: {f.confidence})")

    print()
    print(f"Verifier (Gemini) checked {len(result.verified_flags)} flag(s):")
    for v in result.verified_flags:
        print(f"  - row {v.row_index}: {v.label.value} — {v.verifier_notes}")

    print()
    print("Final flagged rows (rejected flags excluded):", result.flagged_row_indices)
    print(f"Semantic reasoning cycles run: {result.semantic_iterations}")

except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)
