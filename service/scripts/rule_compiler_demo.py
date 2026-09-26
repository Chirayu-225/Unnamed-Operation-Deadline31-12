"""
Live rule compiler demo — makes REAL Groq API calls. Tests both paths:
a clear comparison (should compile to a structured rule) and a
judgment call (should fall back to semantic). Also tests the schema
grounding by asking about a field that doesn't exist.

Run from dbcaas/service, with GROQ_API_KEY set:
    PYTHONPATH=. python3 scripts/rule_compiler_demo.py
"""

from app.agent.llm_clients import GroqClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.rules.compiler import RuleCompiler

table = CanonicalTable(
    tenant_id="demo",
    source_id="demo",
    table_name="transactions",
    columns=[
        ColumnSchema(name="amount", type=ColumnType.FLOAT),
        ColumnSchema(name="refund_flag", type=ColumnType.BOOLEAN),
        ColumnSchema(name="customer_name", type=ColumnType.STRING),
    ],
    rows=[],
)

instructions = [
    ("flag negative amounts", "expect: structured"),
    (
        "flag anything that looks suspicious given the customer's overall pattern",
        "expect: semantic",
    ),
    (
        "flag rows missing a social security number",
        "expect: semantic (no SSN field exists — the compiler should recognize that "
        "and fall back to semantic guidance rather than hallucinate a fake structured "
        "rule; 'failed' would only happen if it stubbornly tried anyway despite being "
        "told not to)",
    ),
]

try:
    compiler = RuleCompiler(GroqClient())
    for instruction, expectation in instructions:
        print(f"Instruction: {instruction!r}  ({expectation})")
        result = compiler.compile(table, instruction)
        print(f"  -> kind: {result.kind}")
        print(f"  -> description: {result.description}")
        if result.compiled_rule:
            for c in result.compiled_rule.conditions:
                print(f"     condition: {c.field} {c.operator.value} {c.value!r}")
        if result.error:
            print(f"  -> error: {result.error}")
        print()

except Exception as e:
    print("FAILED:", type(e).__name__, "-", e)
