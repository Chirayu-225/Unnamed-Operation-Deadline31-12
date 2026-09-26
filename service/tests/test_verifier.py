from app.agent.llm_clients import LLMClient
from app.agent.semantic_reasoning import SemanticFlag
from app.agent.verifier import _VERIFY_CHUNK_SIZE, VerificationLabel, Verifier
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType


class _FakeLLM(LLMClient):
    def __init__(self, canned_response: str):
        self.canned_response = canned_response
        self.last_user_prompt: str | None = None

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.last_user_prompt = user_prompt
        return self.canned_response


class _CallCountingLLM(LLMClient):
    """Confirms every row mentioned in each prompt — used to verify
    chunking splits a large flag list into multiple calls."""

    def __init__(self):
        self.call_count = 0
        self.prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(user_prompt)
        import re

        indices = re.findall(r"Claim about row (\d+)", user_prompt)
        verifications = [
            {"row_index": int(i), "label": "confirmed", "notes": "ok"} for i in indices
        ]
        import json

        return json.dumps({"verifications": verifications})


class _PoisonRowLLM(LLMClient):
    """Simulates a provider that's down specifically for whichever
    chunk contains `poison_row` — every other chunk succeeds
    normally. Used to prove one chunk's total failure doesn't affect
    any other chunk's verification results."""

    def __init__(self, poison_row: int):
        self.poison_row = poison_row
        self.call_count = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        if f"Claim about row {self.poison_row}:" in user_prompt:
            raise RuntimeError("provider down for this chunk")

        import json
        import re

        indices = re.findall(r"Claim about row (\d+)", user_prompt)
        verifications = [
            {"row_index": int(i), "label": "confirmed", "notes": "ok"} for i in indices
        ]
        return json.dumps({"verifications": verifications})


def _table() -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="accounts",
        columns=[
            ColumnSchema(name="company", type=ColumnType.STRING),
            ColumnSchema(name="industry", type=ColumnType.STRING),
        ],
        rows=[
            {"company": "Acme Corp", "industry": "Technology"},
            {"company": "Joe's Bakery", "industry": "Technology"},
        ],
    )


def _flag() -> SemanticFlag:
    return SemanticFlag(row_index=1, reason="bakery listed as tech", confidence=0.8)


def test_empty_flags_returns_empty_without_calling_llm():
    llm = _FakeLLM("should never be called")
    result = Verifier(llm).verify(_table(), [])
    assert result == []


def test_confirms_supported_claim():
    llm = _FakeLLM(
        '{"verifications": [{"row_index": 1, "label": "confirmed", "notes": "bakery is not tech"}]}'
    )
    result = Verifier(llm).verify(_table(), [_flag()])
    assert len(result) == 1
    assert result[0].label == VerificationLabel.CONFIRMED
    assert result[0].reason == "bakery listed as tech"  # original claim preserved
    assert result[0].original_confidence == 0.8


def test_rejects_unsupported_claim():
    llm = _FakeLLM(
        '{"verifications": [{"row_index": 1, "label": "rejected", "notes": "actually fine"}]}'
    )
    result = Verifier(llm).verify(_table(), [_flag()])
    assert result[0].label == VerificationLabel.REJECTED


def test_needs_review_label_passes_through():
    llm = _FakeLLM(
        '{"verifications": [{"row_index": 1, "label": "needs_review", "notes": "unclear"}]}'
    )
    result = Verifier(llm).verify(_table(), [_flag()])
    assert result[0].label == VerificationLabel.NEEDS_REVIEW


def test_fails_safe_to_needs_review_on_malformed_json():
    llm = _FakeLLM("not json at all")
    result = Verifier(llm).verify(_table(), [_flag()])
    assert len(result) == 1
    assert result[0].label == VerificationLabel.NEEDS_REVIEW
    assert result[0].row_index == 1  # original flag data preserved despite failure
    # The LLM DID respond (just unusably) — same bucket as "verifier
    # ran and returned nothing about this row," not a call failure.
    assert result[0].verification_failed is True


def test_fails_safe_to_needs_review_when_row_missing_from_response():
    """LLM responds validly but simply omits this row — should not be
    silently dropped or silently trusted."""
    llm = _FakeLLM('{"verifications": []}')
    result = Verifier(llm).verify(_table(), [_flag()])
    assert len(result) == 1
    assert result[0].label == VerificationLabel.NEEDS_REVIEW
    assert result[0].verification_failed is True


def test_genuine_needs_review_is_not_marked_as_a_technical_failure():
    """The verifier ran, parsed cleanly, and deliberately returned
    "needs_review" as its considered judgment — this must NOT be
    conflated with a call failure, since app.domain.calibration treats
    the two very differently (see test_calibration.py)."""
    llm = _FakeLLM(
        '{"verifications": [{"row_index": 1, "label": "needs_review", "notes": "unclear"}]}'
    )
    result = Verifier(llm).verify(_table(), [_flag()])
    assert result[0].label == VerificationLabel.NEEDS_REVIEW
    assert result[0].verification_failed is False


def test_handles_markdown_fenced_response():
    llm = _FakeLLM(
        '```json\n{"verifications": [{"row_index": 1, "label": "confirmed", "notes": "x"}]}\n```'
    )
    result = Verifier(llm).verify(_table(), [_flag()])
    assert result[0].label == VerificationLabel.CONFIRMED


def test_prompt_includes_actual_row_evidence_marked_untrusted():
    llm = _FakeLLM('{"verifications": []}')
    Verifier(llm).verify(_table(), [_flag()])
    assert "UNTRUSTED DATA" in llm.last_user_prompt
    assert "Joe's Bakery" in llm.last_user_prompt  # real row data, not a paraphrase


def _big_table(n_rows: int) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="accounts",
        columns=[
            ColumnSchema(name="company", type=ColumnType.STRING),
            ColumnSchema(name="industry", type=ColumnType.STRING),
        ],
        rows=[{"company": f"Company {i}", "industry": "Technology"} for i in range(n_rows)],
    )


def test_verify_chunks_a_large_flag_list_into_multiple_calls():
    n_flags = _VERIFY_CHUNK_SIZE * 2 + 5  # forces 3 chunks, not 1
    table = _big_table(n_flags)
    flags = [SemanticFlag(row_index=i, reason="test", confidence=0.5) for i in range(n_flags)]
    llm = _CallCountingLLM()

    result = Verifier(llm).verify(table, flags)

    assert llm.call_count == 3  # ceil(45 / 20) == 3, not one call for all 45
    assert len(result) == n_flags
    assert all(r.label == VerificationLabel.CONFIRMED for r in result)


def test_one_chunk_failing_every_retry_does_not_affect_other_chunks(monkeypatch):
    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)
    n_flags = _VERIFY_CHUNK_SIZE * 2 + 5  # 3 chunks: rows 0-19, 20-39, 40-44
    table = _big_table(n_flags)
    flags = [SemanticFlag(row_index=i, reason="test", confidence=0.5) for i in range(n_flags)]
    poison_row = 25  # lands in the second chunk (20-39)
    llm = _PoisonRowLLM(poison_row=poison_row)

    result = Verifier(llm).verify(table, flags)
    result_by_index = {r.row_index: r for r in result}

    assert len(result) == n_flags  # every flag still gets a result, none dropped
    # First and third chunks succeeded normally.
    assert result_by_index[0].label == VerificationLabel.CONFIRMED
    assert result_by_index[44].label == VerificationLabel.CONFIRMED
    # Second chunk (containing the poison row) failed every retry —
    # every flag in THAT chunk falls back to NEEDS_REVIEW with an
    # explanatory note, but only that chunk's flags.
    assert result_by_index[poison_row].label == VerificationLabel.NEEDS_REVIEW
    assert "verification unavailable" in result_by_index[poison_row].verifier_notes
    # This is the exact path that let a real quota-exhaustion error
    # mid-scan masquerade as a genuine "verifier looked and was
    # uncertain" NEEDS_REVIEW — verification_failed=True is what lets
    # app.domain.calibration tell the two apart.
    assert result_by_index[poison_row].verification_failed is True
    assert result_by_index[20].label == VerificationLabel.NEEDS_REVIEW
    assert result_by_index[20].verification_failed is True
    assert result_by_index[39].label == VerificationLabel.NEEDS_REVIEW
    # 3 attempts spent on the poison chunk before giving up on it.
    assert llm.call_count == 1 + 3 + 1  # chunk1 (1 call) + chunk2 (3 retries) + chunk3 (1 call)


def test_verifies_multiple_flags_independently():
    table = _table()
    flags = [
        SemanticFlag(row_index=0, reason="looks fine", confidence=0.5),
        SemanticFlag(row_index=1, reason="bakery mismatch", confidence=0.9),
    ]
    llm = _FakeLLM(
        '{"verifications": ['
        '{"row_index": 0, "label": "rejected", "notes": "actually fine"}, '
        '{"row_index": 1, "label": "confirmed", "notes": "real mismatch"}'
        "]}"
    )
    result = Verifier(llm).verify(table, flags)
    result_by_index = {r.row_index: r for r in result}
    assert result_by_index[0].label == VerificationLabel.REJECTED
    assert result_by_index[1].label == VerificationLabel.CONFIRMED
