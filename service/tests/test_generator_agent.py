from app.agent.generator import GeneratorAgent
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType, ScanContext


def _leads_table() -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False, semantic_hint="email"),
            ColumnSchema(name="amount", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="account_id", type=ColumnType.INTEGER, nullable=False),
        ],
        rows=[
            {"email": "a@example.com", "amount": 120, "account_id": 1},
            {"email": "", "amount": -40, "account_id": 2},
            {"email": "bob@example.com", "amount": 80, "account_id": 99},
            {"email": "a@example.com", "amount": 120, "account_id": 1},
            {"email": "not-an-email", "amount": 60, "account_id": 2},
            {"email": "c@example.com", "amount": 100000, "account_id": 3},
        ],
    )


def _accounts_table() -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="accounts",
        columns=[ColumnSchema(name="id", type=ColumnType.INTEGER)],
        rows=[{"id": i} for i in (1, 2, 3)],
    )


def test_plan_includes_all_applicable_checks():
    table = _leads_table()
    plan = GeneratorAgent().plan(table)
    check_names = {c.name for c in plan}
    # every check we've built should find something relevant in this table
    assert check_names == {
        "null_check",
        "duplicate_check",
        "format_validity_check",
        "outlier_check",
        "referential_integrity_check",
        "prompt_injection_check",
    }


def test_run_matches_union_of_individual_check_results():
    """The agent's aggregated flags should be exactly the union of what
    each check flags on its own — same numbers we already verified in
    the manual test script, just orchestrated now instead of called
    one at a time."""
    table = _leads_table()
    context = ScanContext(tables=[table, _accounts_table()])

    result = GeneratorAgent().run(table, context)

    # known from prior manual verification: null=[1], dup=[0,3],
    # format=[4], outlier includes amount+account_id outliers, ref=[2]
    assert 1 in result.flagged_row_indices  # null check
    assert 0 in result.flagged_row_indices and 3 in result.flagged_row_indices  # dup
    assert 4 in result.flagged_row_indices  # format
    assert 2 in result.flagged_row_indices  # referential integrity
    assert result.table_name == "leads"
    assert result.total_flagged == len(result.flagged_row_indices)


def test_check_results_are_individually_inspectable():
    table = _leads_table()
    result = GeneratorAgent().run(table)
    result_by_name = {r.check_name: r for r in result.check_results}
    assert "null_check" in result_by_name
    assert result_by_name["null_check"].flagged_row_indices == [1]


def test_run_without_llm_produces_no_semantic_flags():
    table = _leads_table()
    result = GeneratorAgent().run(table)
    assert result.semantic_flags == []


def test_run_with_llm_merges_semantic_flags_into_union():
    from app.agent.llm_clients import LLMClient

    class _FakeLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            # Flags row 5 (not already flagged by any deterministic
            # check in this small table) with a semantic-only reason.
            return '{"flags": [{"row_index": 5, "reason": "looks off", "confidence": 0.7}]}'

    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING, nullable=True)],
        rows=[{"email": f"user{i}@example.com"} for i in range(6)],
    )

    result = GeneratorAgent().run(table, llm=_FakeLLM())
    assert len(result.semantic_flags) == 1
    assert result.semantic_flags[0].row_index == 5
    assert 5 in result.flagged_row_indices


def test_verifier_rejection_excludes_flag_from_union():
    from app.agent.llm_clients import LLMClient

    class _GeneratorLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            return '{"flags": [{"row_index": 5, "reason": "looks off", "confidence": 0.7}]}'

    class _VerifierLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            return '{"verifications": [{"row_index": 5, "label": "rejected", "notes": "actually fine"}]}'

    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING, nullable=True)],
        rows=[{"email": f"user{i}@example.com"} for i in range(6)],
    )

    result = GeneratorAgent().run(table, llm=_GeneratorLLM(), verifier_llm=_VerifierLLM())
    assert len(result.semantic_flags) == 1  # generator still produced it
    assert len(result.verified_flags) == 1
    assert result.verified_flags[0].label.value == "rejected"
    assert 5 not in result.flagged_row_indices  # but rejected -> not counted


def test_verifier_confirmation_keeps_flag_in_union():
    from app.agent.llm_clients import LLMClient

    class _GeneratorLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            return '{"flags": [{"row_index": 5, "reason": "looks off", "confidence": 0.7}]}'

    class _VerifierLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            return '{"verifications": [{"row_index": 5, "label": "confirmed", "notes": "real issue"}]}'

    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING, nullable=True)],
        rows=[{"email": f"user{i}@example.com"} for i in range(6)],
    )

    result = GeneratorAgent().run(table, llm=_GeneratorLLM(), verifier_llm=_VerifierLLM())
    assert 5 in result.flagged_row_indices


def test_verifier_llm_without_generator_llm_has_no_effect():
    """verifier_llm alone (no llm) should not error — nothing to verify."""
    table = _leads_table()
    from app.agent.llm_clients import LLMClient

    class _UnusedLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("should never be called")

    result = GeneratorAgent().run(table, verifier_llm=_UnusedLLM())
    assert result.semantic_flags == []
    assert result.verified_flags == []


def test_structured_custom_instruction_runs_deterministically_no_semantic_call():
    """A custom instruction that compiles to a structured rule should
    be executed exactly, with NO semantic reasoning call made at all —
    it's fully handled, so there's nothing left for the LLM to judge."""
    from app.agent.llm_clients import LLMClient

    calls = []

    class _CompilerAndReasonerLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            calls.append(user_prompt)
            # Only the compiler should ever be called in this test —
            # if semantic reasoning also calls, this canned compiler
            # response would be nonsense to it, proving the leak.
            return (
                '{"kind": "structured", "conditions": '
                '[{"field": "amount", "operator": "less_than", "value": 0}], '
                '"conjunction": "and", "description": "Flag negative amounts"}'
            )

    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="transactions",
        columns=[ColumnSchema(name="amount", type=ColumnType.FLOAT)],
        rows=[{"amount": -10}, {"amount": 50}],
    )

    result = GeneratorAgent().run(
        table, llm=_CompilerAndReasonerLLM(), custom_instruction="flag negative amounts"
    )

    assert len(calls) == 1  # only the compiler ran, no semantic pass
    assert result.compilation is not None
    assert result.compilation.kind == "structured"
    assert 0 in result.flagged_row_indices
    assert any(r.check_name == "custom_rule" for r in result.check_results)
    assert result.semantic_flags == []  # no semantic pass happened


def test_semantic_custom_instruction_passes_compiled_description_to_reasoner():
    from app.agent.llm_clients import LLMClient

    prompts_seen = []

    class _SequentialLLM(LLMClient):
        def __init__(self):
            self.call_count = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.call_count += 1
            prompts_seen.append(user_prompt)
            if self.call_count == 1:
                # compiler call
                return '{"kind": "semantic", "description": "Flag anything unusual for this account history"}'
            # semantic reasoning call
            return '{"flags": [{"row_index": 0, "reason": "unusual", "confidence": 0.6}]}'

    table = _leads_table()
    llm = _SequentialLLM()
    result = GeneratorAgent().run(table, llm=llm, custom_instruction="flag weird stuff")

    assert llm.call_count == 2  # compiler, then semantic reasoning
    assert result.compilation.kind == "semantic"
    assert "Flag anything unusual for this account history" in prompts_seen[1]
    assert len(result.semantic_flags) == 1


def _many_rows_table(n: int) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING, nullable=True)],
        rows=[{"email": f"user{i}@example.com"} for i in range(n)],
    )


def test_full_table_gets_covered_by_default_even_when_every_batch_is_clean():
    """A clean-looking first batch must NOT stop the loop early — full
    coverage is the default now, so a low flag ratio on one batch is
    irrelevant to whether the loop keeps going. This is the exact
    scenario the old ratio-based design got wrong (see the module
    docstring's note on the eval finding): a clean early batch used to
    end the scan before ever looking at the rest of the table."""
    from app.agent.llm_clients import LLMClient

    class _NeverFlagsLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            return '{"flags": []}'

    llm = _NeverFlagsLLM()
    table = _many_rows_table(50)  # 3 batches of 20/20/10 to cover all 50 rows

    # semantic_sample_size pinned explicitly — this test is about the
    # iteration loop's coverage mechanics, not about whatever the
    # production default happens to be tuned to.
    result = GeneratorAgent().run(table, llm=llm, semantic_sample_size=20)

    assert llm.calls == 3  # every row still gets sampled, despite zero flags every batch
    assert result.semantic_iterations == 3


def test_full_table_gets_covered_even_when_every_batch_flags_heavily():
    """The mirror case: a heavily-flagged first batch also doesn't
    change anything now — the loop covers the whole table regardless
    of what any individual batch found, not more and not less."""
    from app.agent.llm_clients import LLMClient

    class _AlwaysFlagsEverythingLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            return (
                '{"flags": ['
                '{"row_index": 0, "reason": "x", "confidence": 0.9}, '
                '{"row_index": 1, "reason": "x", "confidence": 0.9}'
                ']}'
            )

    llm = _AlwaysFlagsEverythingLLM()
    table = _many_rows_table(50)

    result = GeneratorAgent().run(table, llm=llm, semantic_sample_size=20)

    assert llm.calls == 3  # same coverage as the all-clean case above
    assert result.semantic_iterations == 3


def test_iteration_stops_once_the_table_is_exhausted():
    from app.agent.llm_clients import LLMClient

    class _FakeLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            return '{"flags": []}'

    llm = _FakeLLM()
    # 25 rows, sample size 20 -> batch 1 covers 20, batch 2 covers the
    # remaining 5 and exhausts the table -> exactly 2 calls, not a
    # third wasted one once nothing fresh is left.
    table = _many_rows_table(25)

    result = GeneratorAgent().run(table, llm=llm, semantic_sample_size=20)

    assert llm.calls == 2
    assert result.semantic_iterations == 2


def test_max_semantic_llm_calls_caps_coverage_when_explicitly_set():
    """The opt-in cost cap: with max_semantic_llm_calls set, the loop
    stops there even though more of the table remains unsampled — the
    caller's explicit tradeoff, not something the default path does."""
    from app.agent.llm_clients import LLMClient

    class _FakeLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            return '{"flags": []}'

    llm = _FakeLLM()
    table = _many_rows_table(200)  # would need 10 batches for full coverage at size 20

    result = GeneratorAgent().run(table, llm=llm, max_semantic_llm_calls=2, semantic_sample_size=20)

    assert llm.calls == 2  # capped, even though 160 rows were never sampled
    assert result.semantic_iterations == 2


def test_semantic_iterations_is_zero_without_an_llm():
    table = _leads_table()
    result = GeneratorAgent().run(table)
    assert result.semantic_iterations == 0


def test_iteration_flags_from_every_batch_are_all_retained():
    """Flags from batch 1 shouldn't be discarded once batch 2 runs —
    the union should include every batch's findings, across the whole
    table, not just the last one. Which 20 of the 25 rows land in
    batch 1 vs batch 2 is randomized (SemanticReasoner samples
    randomly whenever the pool exceeds the batch size), so the fake
    LLM here flags every row it's actually shown each call — reading
    row indices out of its own prompt — rather than hardcoding a
    specific split, since SemanticReasoner.run now (correctly) drops
    any flag for a row that wasn't part of that batch's sample."""
    import json
    import re

    from app.agent.llm_clients import LLMClient

    class _FlagsEveryRowShownLLM(LLMClient):
        def __init__(self):
            self.calls = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            shown = [int(m) for m in re.findall(r"\] row (\d+):", user_prompt)]
            flags = [{"row_index": i, "reason": "x", "confidence": 0.6} for i in shown]
            return json.dumps({"flags": flags})

    llm = _FlagsEveryRowShownLLM()
    table = _many_rows_table(25)  # 2 batches regardless of split: 20 + 5

    result = GeneratorAgent().run(table, llm=llm, semantic_sample_size=20)

    flagged_rows = {f.row_index for f in result.semantic_flags}
    assert flagged_rows == set(range(25))  # every row covered across both batches
    assert result.semantic_iterations == 2


def test_failed_compilation_falls_back_to_raw_instruction():
    from app.agent.llm_clients import LLMClient

    prompts_seen = []

    class _SequentialLLM(LLMClient):
        def __init__(self):
            self.call_count = 0

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.call_count += 1
            prompts_seen.append(user_prompt)
            if self.call_count == 1:
                return "not valid json"  # compilation fails
            return '{"flags": []}'

    table = _leads_table()
    llm = _SequentialLLM()
    result = GeneratorAgent().run(
        table, llm=llm, custom_instruction="flag the weird ones please"
    )

    assert llm.call_count == 2
    assert result.compilation.kind == "failed"
    assert "flag the weird ones please" in prompts_seen[1]  # raw instruction used as fallback


def test_semantic_layer_stops_gracefully_and_keeps_partial_coverage_on_llm_unavailable(monkeypatch):
    """The product principle this enforces: partial honest results beat
    both a full crash and silently presenting incomplete coverage as
    complete. A provider outage partway through a scan should stop the
    semantic loop, keep whatever coverage earlier batches already
    earned, and say so explicitly — never take down deterministic
    results that already succeeded, and never pretend the whole table
    was covered when it wasn't.

    Which 20 of the 50 rows land in the one successful batch is
    randomized (SemanticReasoner samples randomly whenever the pool
    exceeds the batch size), so the fake LLM flags whichever row it's
    actually shown first, read out of its own prompt, rather than
    hardcoding row_index 0 — SemanticReasoner.run now (correctly) drops
    any flag for a row that wasn't part of that batch's sample, so a
    hardcoded index would flake depending on the random draw."""
    import re

    from app.agent.llm_clients import LLMClient

    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)

    class _DiesAfterFirstBatchLLM(LLMClient):
        def __init__(self):
            self.calls = 0
            self.first_batch_row: int | None = None

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            self.calls += 1
            if self.calls == 1:
                shown = [int(m) for m in re.findall(r"\] row (\d+):", user_prompt)]
                self.first_batch_row = shown[0]
                return (
                    f'{{"flags": [{{"row_index": {shown[0]}, '
                    f'"reason": "looks off", "confidence": 0.7}}]}}'
                )
            raise RuntimeError("provider down")

    llm = _DiesAfterFirstBatchLLM()
    table = _many_rows_table(50)  # 3 batches needed for full coverage; only 1 will succeed

    result = GeneratorAgent().run(table, llm=llm, semantic_sample_size=20)

    # Batch 1 succeeded (1 call). Batch 2's 3 retry attempts (calls
    # 2, 3, 4) all failed, exhausting complete_with_retry, so the loop
    # stopped there rather than crashing the whole scan.
    assert llm.calls == 1 + 3
    assert result.semantic_iterations == 1  # only the one successful batch counted
    assert len(result.semantic_flags) == 1  # batch 1's flag is kept, not discarded
    assert llm.first_batch_row in result.flagged_row_indices

    assert result.semantic_coverage_warning is not None
    assert "1 batch" in result.semantic_coverage_warning
    assert "50" in result.semantic_coverage_warning  # total row count mentioned
    assert "provider down" in result.semantic_coverage_warning


def test_semantic_layer_stops_gracefully_when_even_the_smallest_batch_is_too_large(monkeypatch):
    """SemanticReasoner already shrinks a batch on its own when a 413
    hits (see test_semantic_reasoning.py) — this is the rarer case
    where even its floor size still gets rejected as too large.
    GeneratorAgent should treat that the same way as a provider
    outage: stop the loop, keep whatever coverage already happened,
    and explain why in the warning — not crash the scan."""
    from app.agent.llm_clients import LLMClient

    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)

    class _FakeTooLargeError(Exception):
        def __init__(self):
            super().__init__("Request too large")
            self.status_code = 413

    class _AlwaysTooLargeLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise _FakeTooLargeError()

    table = _many_rows_table(50)
    result = GeneratorAgent().run(table, llm=_AlwaysTooLargeLLM())

    assert result.semantic_iterations == 0
    assert result.semantic_flags == []
    assert result.semantic_coverage_warning is not None
    assert "too large" in result.semantic_coverage_warning.lower()
    assert "50" in result.semantic_coverage_warning


def test_deterministic_checks_are_unaffected_by_semantic_layer_outage(monkeypatch):
    """Deterministic checks run and complete before the semantic loop
    even starts — an LLM outage must not lose results that had nothing
    to do with the LLM in the first place."""
    from app.agent.llm_clients import LLMClient

    monkeypatch.setattr("app.agent.llm_clients.time.sleep", lambda _: None)

    class _AlwaysDownLLM(LLMClient):
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("provider down")

    table = _leads_table()  # has real deterministic issues (nulls, dupes, etc.)
    result = GeneratorAgent().run(table, llm=_AlwaysDownLLM())

    # Same deterministic flags as the no-LLM-at-all case — the outage
    # cost the scan its semantic coverage, not its deterministic one.
    assert 1 in result.flagged_row_indices  # null check
    assert 0 in result.flagged_row_indices and 3 in result.flagged_row_indices  # dup
    assert result.semantic_coverage_warning is not None
    assert result.semantic_iterations == 0  # not even the first batch got through
