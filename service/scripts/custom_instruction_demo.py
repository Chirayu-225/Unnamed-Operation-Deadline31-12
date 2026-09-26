"""
Live custom instruction demo — makes REAL Groq (and for one case,
Gemini) API calls. Shows the full custom_instruction flow: an
instruction that should compile to a structured rule (deterministic
execution, no semantic call at all) and one that should fall back to
semantic guidance (with verification).

Run from dbcaas/service, with GROQ_API_KEY and GEMINI_API_KEY set:
    PYTHONPATH=. python3 scripts/custom_instruction_demo.py
"""

from app.agent.generator import GeneratorAgent
from app.agent.llm_clients import GeminiClient, GroqClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType

transactions = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="transactions",
    columns=[
        ColumnSchema(name="amount", type=ColumnType.FLOAT),
        ColumnSchema(name="customer", type=ColumnType.STRING),
    ],
    rows=[
        {"amount": 150, "customer": "Acme Corp"},
        {"amount": -75, "customer": "Globex Inc"},
        {"amount": 200, "customer": "Initech"},
    ],
)

print("=== Case 1: structured instruction (should skip semantic reasoning entirely) ===")
try:
    result = GeneratorAgent().run(
        transactions, llm=GroqClient(), custom_instruction="flag any negative amount"
    )
    print("Compilation kind:", result.compilation.kind)
    print("Compilation description:", result.compilation.description)
    print("Custom rule results:", [r.detail for r in result.check_results if r.check_name == "custom_rule"])
    print("Semantic flags (should be empty — fully handled deterministically):", result.semantic_flags)
    print("Final flagged rows:", result.flagged_row_indices)
except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)

print()
print("=== Case 2: judgment-call instruction (should fall back to semantic + verifier) ===")
accounts = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="accounts",
    columns=[
        ColumnSchema(name="company", type=ColumnType.STRING),
        ColumnSchema(name="industry", type=ColumnType.STRING),
    ],
    rows=[
        {"company": "Acme Software Inc", "industry": "Technology"},
        {"company": "Joe's Bakery", "industry": "Technology"},
    ],
)
try:
    result = GeneratorAgent().run(
        accounts,
        llm=GroqClient(),
        verifier_llm=GeminiClient(),
        custom_instruction="flag companies whose name doesn't match their listed industry",
    )
    print("Compilation kind:", result.compilation.kind)
    print("Compilation description:", result.compilation.description)
    print("Semantic flags:", [(f.row_index, f.reason) for f in result.semantic_flags])
    print("Verified flags:", [(v.row_index, v.label.value) for v in result.verified_flags])
    print("Final flagged rows:", result.flagged_row_indices)
except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)
