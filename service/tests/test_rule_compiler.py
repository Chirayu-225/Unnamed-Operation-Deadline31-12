from app.agent.llm_clients import LLMClient
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.rules.compiler import RuleCompiler
from app.rules.dsl import Operator


class _FakeLLM(LLMClient):
    def __init__(self, canned_response: str):
        self.canned_response = canned_response
        self.last_user_prompt: str | None = None

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.last_user_prompt = user_prompt
        return self.canned_response


def _table() -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="transactions",
        columns=[
            ColumnSchema(name="amount", type=ColumnType.FLOAT),
            ColumnSchema(name="refund_flag", type=ColumnType.BOOLEAN),
        ],
        rows=[],
    )


def test_compiles_structured_rule():
    llm = _FakeLLM(
        '{"kind": "structured", "conditions": ['
        '{"field": "amount", "operator": "less_than", "value": 0}'
        '], "conjunction": "and", "description": "Flag negative amounts"}'
    )
    result = RuleCompiler(llm).compile(_table(), "flag negative amounts")

    assert result.kind == "structured"
    assert result.compiled_rule is not None
    assert result.compiled_rule.conditions[0].field == "amount"
    assert result.compiled_rule.conditions[0].operator == Operator.LESS_THAN
    assert result.description == "Flag negative amounts"


def test_compiles_multi_condition_structured_rule():
    llm = _FakeLLM(
        '{"kind": "structured", "conditions": ['
        '{"field": "amount", "operator": "less_than", "value": 0}, '
        '{"field": "refund_flag", "operator": "equals", "value": false}'
        '], "conjunction": "and", "description": "Negative amount without refund flag"}'
    )
    result = RuleCompiler(llm).compile(
        _table(), "flag negative amounts that aren't refunds"
    )
    assert result.kind == "structured"
    assert len(result.compiled_rule.conditions) == 2


def test_falls_back_to_semantic_for_judgment_calls():
    llm = _FakeLLM(
        '{"kind": "semantic", "description": "Flag transactions that look suspicious for this accounts history"}'
    )
    result = RuleCompiler(llm).compile(
        _table(), "flag anything that looks suspicious given history"
    )
    assert result.kind == "semantic"
    assert result.semantic_instruction is not None
    assert result.compiled_rule is None


def test_rejects_rule_referencing_unknown_field():
    """Schema grounding — a hallucinated field name should fail
    compilation, not silently produce a rule that will no-op."""
    llm = _FakeLLM(
        '{"kind": "structured", "conditions": ['
        '{"field": "customer_ssn", "operator": "is_null", "value": null}'
        '], "conjunction": "and", "description": "Flag missing SSN"}'
    )
    result = RuleCompiler(llm).compile(_table(), "flag rows missing SSN")
    assert result.kind == "failed"
    assert "customer_ssn" in result.error


def test_fails_safe_on_malformed_json():
    llm = _FakeLLM("not json at all")
    result = RuleCompiler(llm).compile(_table(), "flag bad rows")
    assert result.kind == "failed"
    assert result.error is not None


def test_fails_safe_on_empty_conditions():
    llm = _FakeLLM('{"kind": "structured", "conditions": [], "description": "empty"}')
    result = RuleCompiler(llm).compile(_table(), "flag something")
    assert result.kind == "failed"


def test_handles_markdown_fenced_response():
    llm = _FakeLLM(
        '```json\n{"kind": "semantic", "description": "use judgment"}\n```'
    )
    result = RuleCompiler(llm).compile(_table(), "use your judgment")
    assert result.kind == "semantic"


def test_instruction_is_framed_as_untrusted_in_prompt():
    llm = _FakeLLM('{"kind": "semantic", "description": "x"}')
    RuleCompiler(llm).compile(_table(), "some instruction")
    assert "UNTRUSTED DATA" in llm.last_user_prompt


def test_compiled_rule_source_is_user_authored():
    llm = _FakeLLM(
        '{"kind": "structured", "conditions": ['
        '{"field": "amount", "operator": "greater_than", "value": 1000}'
        '], "description": "Large amounts"}'
    )
    result = RuleCompiler(llm).compile(_table(), "flag large amounts")
    assert result.compiled_rule.source.value == "user_authored"
