"""
Generator agent — planner + tool execution.

This is deliberately the FIRST increment of the agent, with no LLM
involved yet. The "plan" step here is rule-based: ask every registered
check whether it applies to this table (via `applies_to()`), and run
the ones that do. This is intentionally the same orchestration Phase 1
would have needed for a standalone scan endpoint — building it here
avoids building it twice.

The LLM semantic reasoning layer gets added as a second increment on
top of this, once API keys are wired in. When that happens, `plan()`
is the method that grows — swapping "run every applicable check" for
"reason about which checks matter and whether semantic judgment is
also needed" — everything downstream (execute, result aggregation)
stays the same, which is the point of separating these steps.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agent.llm_clients import LLMClient, LLMRequestTooLargeError, LLMUnavailableError
from app.agent.semantic_reasoning import SemanticFlag, SemanticReasoner
from app.agent.verifier import VerificationLabel, VerifiedFlag, Verifier
from app.canonical.models import CanonicalTable, ScanContext
from app.checks.base import Check, CheckResult, all_checks
from app.rules.compiler import CompilationResult, RuleCompiler
from app.rules.executor import execute_rule

# Semantic coverage policy: by default, the semantic layer reasons
# over EVERY row of the table, not a bounded sample. This was a
# deliberate redesign, not the original design — an earlier version
# capped at 3 cycles of 20 rows and only kept going past the first
# cycle if that cycle's flag ratio looked suspicious. A real
# evaluation run against forged ground-truth data (see
# eval/run_eval.py) showed what that actually meant in practice: on a
# 150-row table, whole regions were structurally never reasoned over
# at all, every single run, regardless of iteration count — not a
# tuning problem, a coverage ceiling. Since genuine LLM semantic
# judgment (not just deterministic rule-checking) is the product's
# stated differentiator against Validity/RingLead/Cloudingo/Insycle, a
# detection layer that only ever looks at part of the data undercuts
# that claim no matter how well the sampling is tuned. `max_llm_calls`
# below is the explicit, opt-in way a caller trades coverage for cost
# on a very large table — the method itself never silently caps.

# Default rows-per-batch for a real scan (distinct from
# SemanticReasoner's own bare-constructor default of 20, which exists
# for tests/direct use and is left alone). This number comes from a
# live batch-size sweep (eval/run_eval.py) against 3 forged datasets:
# size 20 (the original guess) gave recall 0.756-0.896; size 100 hit
# Groq's per-request token cap and auto-shrank (see
# LLMRequestTooLargeError in llm_clients.py) down to roughly 48-50
# rows/call in practice, and recall at that landing size was as good
# or better across all 3 datasets (0.854-1.0), likely because bigger
# batches give the model more rows to cross-reference against each
# other, which its own prompt asks it to do. 45 is a deliberately
# round, slightly conservative pick near that observed landing zone —
# not the literal number any one run converged on, since that varies
# by dataset content length and this needs to hold up across datasets
# this project hasn't tested yet. The shrink-on-413 safety net stays
# in place regardless, so an unusually verbose dataset still degrades
# gracefully instead of failing outright.
_DEFAULT_PRODUCTION_SAMPLE_SIZE = 45


class ScanResult(BaseModel):
    """The generator agent's output for one table: every deterministic
    check that ran (including a compiled custom rule, if one applied),
    any semantic flags from the LLM layer, any verification results,
    the compilation outcome for a custom instruction (if one was
    given, so a caller can show "here's what I understood" even when
    the eventual UI for confirm-before-run doesn't exist yet), and a
    de-duplicated union of every flagged row index.

    When verification ran, REJECTED semantic flags are excluded from
    `flagged_row_indices` — an unverified claim from the generator
    alone is not treated the same as a check-passed result. NEEDS_REVIEW
    flags stay included; they're uncertain, not dismissed.

    `semantic_coverage_warning` is set (non-None) only when the LLM
    provider became unavailable partway through covering the table —
    every retry on some batch failed, so the loop stopped early rather
    than crash the whole scan. Deterministic results and whatever
    semantic coverage was gathered before that point are still real
    and still returned; this field is what tells a caller the semantic
    layer's coverage is honestly incomplete, not silently partial."""

    table_name: str
    source_id: str
    check_results: list[CheckResult]
    semantic_flags: list[SemanticFlag] = []
    verified_flags: list[VerifiedFlag] = []
    compilation: CompilationResult | None = None
    flagged_row_indices: list[int]
    semantic_iterations: int = 0
    semantic_coverage_warning: str | None = None

    @property
    def total_flagged(self) -> int:
        return len(self.flagged_row_indices)


class GeneratorAgent:
    """Plan + execute, over the deterministic check registry, plus an
    optional semantic reasoning layer when an LLM client is supplied.
    Without an `llm`, this behaves exactly as the rule-based-only
    version did — the semantic layer is additive, never required."""

    def plan(self, table: CanonicalTable, context: ScanContext | None = None) -> list[Check]:
        """Which deterministic checks apply to this table. Still
        rule-based — every registered check gets asked `applies_to()`.
        This governs the deterministic layer only; the semantic layer
        below always runs (on a sample) when an LLM client is given,
        since judgment calls aren't a yes/no 'does this apply'
        question the way a deterministic check's relevance is."""
        instances = [check_cls() for check_cls in all_checks()]
        return [c for c in instances if c.applies_to(table, context)]

    def execute(
        self, table: CanonicalTable, checks: list[Check], context: ScanContext | None = None
    ) -> list[CheckResult]:
        """Run each planned check as a 'tool' and collect its result."""
        return [check.run(table, context) for check in checks]

    def _run_semantic_with_iteration(
        self,
        table: CanonicalTable,
        llm: LLMClient,
        instruction: str | None,
        max_llm_calls: int | None = None,
        sample_size: int | None = None,
    ) -> tuple[list[SemanticFlag], int, str | None]:
        """Batches through the semantic reasoner until every row in the
        table has been sampled at least once — full coverage by
        default, not a bounded look. Each cycle explicitly excludes
        every index already sampled, so every batch is genuinely new
        rows the layer hasn't judged yet; the loop stops only once
        nothing fresh is left to offer (or the optional cost cap below
        is hit).

        `max_llm_calls`, when given, is an explicit opt-in ceiling on
        how many batches run — a caller's deliberate cost/latency
        tradeoff for a very large table, never something this method
        decides on its own. None (the default) means no ceiling: every
        row gets reasoned over.

        If a batch's LLM call fails every retry attempt
        (`LLMUnavailableError` — see `LLMClient.complete_with_retry`),
        the loop stops there rather than crashing the whole scan.
        Whatever flags and coverage earlier batches already produced
        are kept and returned as-is; the third return value carries a
        human-readable warning explaining coverage stopped early, so
        the caller can be honest about it rather than presenting
        partial coverage as if it were complete.

        Verification still happens exactly once, over the union of
        everything every batch in this loop produced, by the caller.

        `sample_size`, when given, overrides SemanticReasoner's default
        rows-per-batch (20) — this is the knob for the empirical
        batch-size sweep against the eval harness: run the same
        dataset at a few sizes, compare precision/recall, pick the
        largest size where detection quality hasn't measurably
        dropped, rather than guessing a number."""
        reasoner = SemanticReasoner(llm, **({"sample_size": sample_size} if sample_size else {}))
        all_flags: list[SemanticFlag] = []
        sampled_indices: set[int] = set()
        calls_made = 0
        total_rows = len(table.rows)
        coverage_warning: str | None = None

        while len(sampled_indices) < total_rows:
            if max_llm_calls is not None and calls_made >= max_llm_calls:
                break

            try:
                result = reasoner.run(table, instruction, exclude_indices=sampled_indices)
            except LLMUnavailableError as exc:
                rows_left = total_rows - len(sampled_indices)
                coverage_warning = (
                    f"Semantic reasoning stopped early after {calls_made} batch(es) "
                    f"({len(sampled_indices)}/{total_rows} rows covered) — the LLM "
                    f"provider was unavailable after retrying: {exc}. {rows_left} "
                    f"row(s) were not reasoned over this scan."
                )
                break
            except LLMRequestTooLargeError as exc:
                # SemanticReasoner already tried shrinking its own batch
                # down to its floor size before giving up — reaching
                # here means even that floor was rejected as too large
                # (e.g. one row's own content is unusually huge), a
                # genuinely different situation from "provider is
                # down." Same fail-safe treatment either way: stop,
                # keep whatever coverage earlier batches already
                # produced, and say so honestly rather than pretending
                # this table has no more issues than what was found.
                rows_left = total_rows - len(sampled_indices)
                coverage_warning = (
                    f"Semantic reasoning stopped early after {calls_made} batch(es) "
                    f"({len(sampled_indices)}/{total_rows} rows covered) — even the "
                    f"smallest batch size was rejected as too large by the provider: "
                    f"{exc}. {rows_left} row(s) were not reasoned over this scan."
                )
                break
            calls_made += 1

            if result.rows_sampled == 0:
                # Defensive — exclude_indices already guarantees this
                # shouldn't happen while sampled_indices < total_rows,
                # but never spend a call's result on nothing to show
                # for it, and never loop forever if it somehow does.
                break

            all_flags.extend(result.flags)
            sampled_indices.update(result.sampled_indices)

        return all_flags, calls_made, coverage_warning

    def run(
        self,
        table: CanonicalTable,
        context: ScanContext | None = None,
        llm: LLMClient | None = None,
        custom_instruction: str | None = None,
        verifier_llm: LLMClient | None = None,
        max_semantic_llm_calls: int | None = None,
        semantic_sample_size: int | None = None,
    ) -> ScanResult:
        """Plan then execute the deterministic checks. If `llm` is
        given:
        - No `custom_instruction`: autonomous semantic reasoning runs,
          same as before — the agent decides what looks wrong on its
          own.
        - `custom_instruction` given: it's compiled first. A
          STRUCTURED result is executed deterministically (precise,
          cheap, no semantic pass needed for it) and its flags are
          added directly to check_results — no LLM judgment call
          required for something a rule can already express exactly.
          A SEMANTIC result passes the compiler's refined description
          to the reasoning layer as guidance. A FAILED compilation
          falls back to passing the user's raw instruction straight
          to the reasoning layer, best-effort, rather than doing
          nothing with it.

        Semantic reasoning covers the WHOLE table by default (see
        `_run_semantic_with_iteration`) — `max_semantic_llm_calls`
        is the explicit opt-in to cap that for cost/latency on a very
        large table; leave it None for full coverage.

        If `verifier_llm` is ALSO given, semantic flags (autonomous or
        guided — never the deterministic custom-rule path, which needs
        no verification) get checked before counting."""
        checks = self.plan(table, context)
        results = self.execute(table, checks, context)

        flagged: set[int] = set()
        for r in results:
            flagged.update(r.flagged_row_indices)

        semantic_flags: list[SemanticFlag] = []
        verified_flags: list[VerifiedFlag] = []
        compilation: CompilationResult | None = None
        semantic_iterations = 0
        semantic_coverage_warning: str | None = None

        if llm is not None:
            effective_instruction = custom_instruction

            if custom_instruction is not None:
                compilation = RuleCompiler(llm).compile(table, custom_instruction)
                if compilation.kind == "structured":
                    rule_result = execute_rule(table, compilation.compiled_rule)
                    results.append(rule_result)
                    flagged.update(rule_result.flagged_row_indices)
                    effective_instruction = None  # fully handled — no semantic pass needed
                elif compilation.kind == "semantic":
                    effective_instruction = compilation.semantic_instruction
                # "failed" -> effective_instruction stays as the raw
                # custom_instruction, best-effort fallback.

            # Run semantic reasoning unless the instruction was fully
            # handled deterministically above. Covers both paths that
            # can reach it — autonomous (no custom_instruction at all)
            # and instruction-guided (compiled to "semantic" or fell
            # back after a failed compilation) — through the one
            # shared `effective_instruction` value.
            if custom_instruction is None or effective_instruction is not None:
                # None means "no explicit override" — resolved here
                # (not left to SemanticReasoner's own bare-constructor
                # default of 20) so both an omitted argument AND an
                # explicit `semantic_sample_size=None` (e.g. the eval
                # harness's SEMANTIC_SAMPLE_SIZE-unset case) land on the
                # same evidence-based production default.
                effective_sample_size = (
                    semantic_sample_size
                    if semantic_sample_size is not None
                    else _DEFAULT_PRODUCTION_SAMPLE_SIZE
                )
                semantic_flags, semantic_iterations, semantic_coverage_warning = (
                    self._run_semantic_with_iteration(
                        table,
                        llm,
                        effective_instruction,
                        max_llm_calls=max_semantic_llm_calls,
                        sample_size=effective_sample_size,
                    )
                )

                if verifier_llm is not None and semantic_flags:
                    # Verifier.verify already fails safe internally
                    # per-chunk (NEEDS_REVIEW on an unavailable chunk,
                    # not a crash) — nothing more to catch here.
                    verified_flags = Verifier(verifier_llm).verify(table, semantic_flags)
                    flagged.update(
                        v.row_index
                        for v in verified_flags
                        if v.label != VerificationLabel.REJECTED
                    )
                else:
                    flagged.update(f.row_index for f in semantic_flags)

        return ScanResult(
            table_name=table.table_name,
            source_id=table.source_id,
            check_results=results,
            semantic_flags=semantic_flags,
            verified_flags=verified_flags,
            compilation=compilation,
            flagged_row_indices=sorted(flagged),
            semantic_iterations=semantic_iterations,
            semantic_coverage_warning=semantic_coverage_warning,
        )
