from app.agent.generator import ScanResult
from app.agent.semantic_reasoning import SemanticFlag
from app.agent.verifier import VerificationLabel, VerifiedFlag
from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.checks.base import CheckResult, MetricCategory
from app.scoring.scorer import compute_scorecard


def _table(n_rows: int, columns: list[ColumnSchema] | None = None) -> CanonicalTable:
    """A table with n dummy rows — for tests that only care about row
    count, not schema. Tests that need specific columns (for
    criticality weighting) pass their own `columns`."""
    cols = columns or [ColumnSchema(name="dummy", type=ColumnType.STRING)]
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="test_table",
        columns=cols,
        rows=[{c.name: "x" for c in cols} for _ in range(n_rows)],
    )


def _scan_result(check_results=None, semantic_flags=None, verified_flags=None) -> ScanResult:
    all_flagged = set()
    for r in check_results or []:
        all_flagged.update(r.flagged_row_indices)
    for f in semantic_flags or []:
        # mirror what GeneratorAgent does: exclude rejected from the union
        verified = {v.row_index: v for v in (verified_flags or [])}.get(f.row_index)
        if verified is None or verified.label != VerificationLabel.REJECTED:
            all_flagged.add(f.row_index)

    return ScanResult(
        table_name="test_table",
        source_id="s",
        check_results=check_results or [],
        semantic_flags=semantic_flags or [],
        verified_flags=verified_flags or [],
        flagged_row_indices=sorted(all_flagged),
    )


def test_perfect_data_scores_100_across_the_board():
    scan = _scan_result()
    card = compute_scorecard(scan, _table(10))
    assert card.overall_score == 100.0
    assert all(m.score == 100.0 for m in card.metric_scores)


def test_deterministic_flag_reduces_its_metric_score():
    check = CheckResult(
        check_name="null_check",
        metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0, 1],
        total_rows_evaluated=10,
        detail="2 missing",
    )
    scan = _scan_result(check_results=[check])
    card = compute_scorecard(scan, _table(10))

    completeness = next(m for m in card.metric_scores if m.metric == MetricCategory.COMPLETENESS)
    assert completeness.score == 80.0  # 1 - 2/10 = 0.8 -> 80

    validity = next(m for m in card.metric_scores if m.metric == MetricCategory.VALIDITY)
    assert validity.score == 100.0


def test_row_flagged_by_two_checks_same_metric_not_double_counted():
    check1 = CheckResult(
        check_name="check1", metric=MetricCategory.VALIDITY,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
    )
    check2 = CheckResult(
        check_name="check2", metric=MetricCategory.VALIDITY,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
    )
    scan = _scan_result(check_results=[check1, check2])
    card = compute_scorecard(scan, _table(10))

    validity = next(m for m in card.metric_scores if m.metric == MetricCategory.VALIDITY)
    assert validity.flagged_weight == 1.0  # not 2.0 — max(), not sum()
    assert validity.score == 90.0


def test_confirmed_semantic_flag_counts_full_weight():
    flag = SemanticFlag(row_index=0, reason="x", confidence=0.9)
    verified = VerifiedFlag(
        row_index=0, reason="x", original_confidence=0.9,
        label=VerificationLabel.CONFIRMED, verifier_notes="checked",
    )
    scan = _scan_result(semantic_flags=[flag], verified_flags=[verified])
    card = compute_scorecard(scan, _table(10))

    accuracy = next(m for m in card.metric_scores if m.metric == MetricCategory.ACCURACY)
    assert accuracy.flagged_weight == 1.0
    assert accuracy.score == 90.0


def test_needs_review_semantic_flag_counts_half_weight():
    flag = SemanticFlag(row_index=0, reason="x", confidence=0.5)
    verified = VerifiedFlag(
        row_index=0, reason="x", original_confidence=0.5,
        label=VerificationLabel.NEEDS_REVIEW, verifier_notes="unclear",
    )
    scan = _scan_result(semantic_flags=[flag], verified_flags=[verified])
    card = compute_scorecard(scan, _table(10))

    accuracy = next(m for m in card.metric_scores if m.metric == MetricCategory.ACCURACY)
    assert accuracy.flagged_weight == 0.5
    assert accuracy.score == 95.0


def test_rejected_semantic_flag_contributes_nothing():
    flag = SemanticFlag(row_index=0, reason="x", confidence=0.8)
    verified = VerifiedFlag(
        row_index=0, reason="x", original_confidence=0.8,
        label=VerificationLabel.REJECTED, verifier_notes="actually fine",
    )
    scan = _scan_result(semantic_flags=[flag], verified_flags=[verified])
    card = compute_scorecard(scan, _table(10))

    accuracy = next(m for m in card.metric_scores if m.metric == MetricCategory.ACCURACY)
    assert accuracy.flagged_weight == 0.0
    assert accuracy.score == 100.0


def test_unverified_semantic_flag_defaults_to_half_weight():
    flag = SemanticFlag(row_index=0, reason="x", confidence=0.95)
    scan = _scan_result(semantic_flags=[flag])
    card = compute_scorecard(scan, _table(10))

    accuracy = next(m for m in card.metric_scores if m.metric == MetricCategory.ACCURACY)
    assert accuracy.flagged_weight == 0.5


def test_custom_metric_weights_change_overall_score():
    check = CheckResult(
        check_name="null_check", metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0, 1, 2, 3, 4], total_rows_evaluated=10, detail="",
    )
    scan = _scan_result(check_results=[check])

    equal_weights = compute_scorecard(scan, _table(10))
    heavy_completeness = compute_scorecard(
        scan, _table(10), metric_weights={MetricCategory.COMPLETENESS: 10.0}
    )
    assert heavy_completeness.overall_score < equal_weights.overall_score


def test_zero_total_rows_does_not_crash_and_scores_100():
    scan = _scan_result()
    card = compute_scorecard(scan, _table(0))
    assert card.overall_score == 100.0


def test_score_never_goes_negative_even_if_flags_exceed_rows():
    check = CheckResult(
        check_name="x", metric=MetricCategory.VALIDITY,
        flagged_row_indices=[0, 1, 2], total_rows_evaluated=2, detail="",
    )
    scan = _scan_result(check_results=[check])
    card = compute_scorecard(scan, _table(2))
    validity = next(m for m in card.metric_scores if m.metric == MetricCategory.VALIDITY)
    assert validity.score == 0.0


# --- Field-criticality weighting ---------------------------------------

def _completeness_table() -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t", source_id="s", table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),  # required
            ColumnSchema(name="notes", type=ColumnType.STRING, nullable=True),   # optional
        ],
        rows=[{"email": "a@x.com", "notes": "x"} for _ in range(10)],
    )


def test_flag_on_required_field_weighs_double_an_optional_one():
    """Core criticality claim: the SAME single flagged row should cost
    the score twice as much when the cause is a required field vs an
    optional one — verified as two independent scenarios, not just
    inferred from the weighting constants."""
    table = _completeness_table()

    required_flag_check = CheckResult(
        check_name="null_check", metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
        flagged_fields={0: ["email"]},
    )
    optional_flag_check = CheckResult(
        check_name="null_check", metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
        flagged_fields={0: ["notes"]},
    )

    required_card = compute_scorecard(_scan_result(check_results=[required_flag_check]), table)
    optional_card = compute_scorecard(_scan_result(check_results=[optional_flag_check]), table)

    required_completeness = next(
        m for m in required_card.metric_scores if m.metric == MetricCategory.COMPLETENESS
    )
    optional_completeness = next(
        m for m in optional_card.metric_scores if m.metric == MetricCategory.COMPLETENESS
    )

    assert required_completeness.flagged_weight == 2.0
    assert optional_completeness.flagged_weight == 1.0
    assert required_completeness.score < optional_completeness.score
    assert required_completeness.score == 80.0  # 1 - 2/10
    assert optional_completeness.score == 90.0  # 1 - 1/10


def test_row_flagged_on_both_required_and_optional_field_takes_the_higher_weight():
    table = _completeness_table()
    check = CheckResult(
        check_name="null_check", metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
        flagged_fields={0: ["notes", "email"]},
    )
    card = compute_scorecard(_scan_result(check_results=[check]), table)
    completeness = next(m for m in card.metric_scores if m.metric == MetricCategory.COMPLETENESS)
    assert completeness.flagged_weight == 2.0  # required field's weight wins, not 3.0


def test_check_without_field_attribution_falls_back_to_flat_weight():
    """A check that doesn't populate flagged_fields (like
    DuplicateCheck) must behave exactly as it did before this feature
    existed — flat weight 1.0, not penalized or rewarded for missing
    attribution."""
    table = _completeness_table()
    check = CheckResult(
        check_name="duplicate_check", metric=MetricCategory.UNIQUENESS,
        flagged_row_indices=[0, 1], total_rows_evaluated=10, detail="",
    )
    card = compute_scorecard(_scan_result(check_results=[check]), table)
    uniqueness = next(m for m in card.metric_scores if m.metric == MetricCategory.UNIQUENESS)
    assert uniqueness.flagged_weight == 2.0  # 2 rows * flat weight 1.0 each
    assert uniqueness.score == 80.0


def test_unknown_field_name_defaults_to_optional_weight_not_a_crash():
    table = _completeness_table()
    check = CheckResult(
        check_name="weird_check", metric=MetricCategory.VALIDITY,
        flagged_row_indices=[0], total_rows_evaluated=10, detail="",
        flagged_fields={0: ["nonexistent_field"]},
    )
    card = compute_scorecard(_scan_result(check_results=[check]), table)
    validity = next(m for m in card.metric_scores if m.metric == MetricCategory.VALIDITY)
    assert validity.flagged_weight == 1.0


def test_criticality_weighting_end_to_end_with_real_null_check():
    """Integration check: run the actual NullCheck (not a hand-built
    CheckResult) through the real scorer, confirming the two layers
    actually connect correctly.

    Note: NullCheck only ever flags REQUIRED fields — a blank optional
    field isn't a completeness violation at all, by definition. So row
    2 below (blank optional "notes") is never flagged by NullCheck in
    the first place; only row 1 (blank required "email") is. This test
    initially assumed otherwise and the failure caught that assumption
    error, not a scorer bug — worth keeping the note so the reasoning
    doesn't get lost."""
    from app.checks.completeness import NullCheck

    table = CanonicalTable(
        tenant_id="t", source_id="s", table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),
            ColumnSchema(name="notes", type=ColumnType.STRING, nullable=True),
        ],
        rows=[
            {"email": "a@x.com", "notes": "ok"},   # clean
            {"email": "", "notes": "ok"},            # required field missing -> flagged
            {"email": "b@x.com", "notes": ""},       # optional field blank -> NOT flagged (allowed)
        ],
    )
    result = NullCheck().run(table)
    assert result.flagged_row_indices == [1]  # only the required-field violation

    scan = _scan_result(check_results=[result])
    card = compute_scorecard(scan, table)

    completeness = next(m for m in card.metric_scores if m.metric == MetricCategory.COMPLETENESS)
    assert completeness.flagged_weight == 2.0  # row 1's required-field weight
    assert completeness.score == round(100 * (1 - 2 / 3), 1)
