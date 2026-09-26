"""
Live semantic reasoning demo — makes a REAL Groq API call. Unlike the
deterministic checks, this can't be verified in advance for you: LLM
output isn't fully deterministic, so what you see may vary slightly
run to run. What SHOULD stay consistent: it should flag row 2 (a
bakery listed under "Technology"), since that's a semantic mismatch no
deterministic check in this system could catch — null/duplicate/format/
outlier/referential-integrity checks all have no way to know a bakery
"looks wrong" under a tech industry label.

Run from dbcaas/service, with GROQ_API_KEY set:
    PYTHONPATH=. python3 scripts/semantic_reasoning_demo.py
"""

from app.agent.generator import GeneratorAgent
from app.agent.llm_clients import GroqClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType

table = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="accounts",
    columns=[
        ColumnSchema(name="company", type=ColumnType.STRING),
        ColumnSchema(name="industry", type=ColumnType.STRING),
    ],
    rows=[
        {"company": "Acme Software Inc", "industry": "Technology"},
        {"company": "Globex Data Systems", "industry": "Technology"},
        {"company": "Joe's Bakery", "industry": "Technology"},  # the semantic mismatch
        {"company": "Initech Cloud Solutions", "industry": "Technology"},
    ],
)

print("Running semantic reasoning against 4 rows (no custom instruction —")
print("autonomous fallback mode, agent decides what looks wrong on its own)...")
print()

try:
    agent = GeneratorAgent()
    result = agent.run(table, llm=GroqClient())

    print("Semantic flags found:")
    if not result.semantic_flags:
        print("  (none — try re-running, LLM output can vary)")
    for flag in result.semantic_flags:
        print(f"  - row {flag.row_index}: {flag.reason} (confidence: {flag.confidence})")

    print()
    print("Full flagged row union (deterministic + semantic):", result.flagged_row_indices)

except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)
