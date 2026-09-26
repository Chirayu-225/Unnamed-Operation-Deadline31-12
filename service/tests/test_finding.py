from app.checks.base import CheckResult, MetricCategory
from app.domain.finding import (
    CheckType,
    Severity,
    VerificationStatus,
    findings_from_check_result,
    findings_from_cross_table_semantic,
    findings_from_semantic_flags,
    generate_finding_id,
)


class _FakeSemanticFlag:
    def __init__(self, row_index, reason, confidence):
        self.row_index = row_index
        self.reason = reason
        self.confidence = confidence


class _FakeVerifiedFlag:
    def __init__(self, row_index, label, verifier_notes=""):
        self.row_index = row_index
        self.label = label
        self.verifier_notes = verifier_notes


class _FakeLabel:
    """Stand-in for VerificationLabel — only needs a `.value` matching
    one of "confirmed"/"needs_review"/"rejected", since the converter
    is deliberately duck-typed to avoid a circular import."""

    def __init__(self, value):
        self.value = value


class _FakeCrossTableFinding:
    def __init__(self, from_table, from_row_index, to_table, to_row_index, fk_column, reason,
                 confidence, verification_label=None, verification_notes=None):
        self.from_table = from_table
        self.from_row_index = from_row_index
        self.to_table = to_table
        self.to_row_index = to_row_index
        self.fk_column = fk_column
        self.reason = reason
        self.confidence = confidence
        self.verification_label = verification_label
        self.verification_notes = verification_notes


# --- generate_finding_id ---------------------------------------------------

def test_hash_is_deterministic_across_calls():
    a = generate_finding_id("deterministic", "validity", "leads", [3], ["email"])
    b = generate_finding_id("deterministic", "validity", "leads", [3], ["email"])
    assert a == b


def test_hash_is_order_independent_for_fields_and_rows():
    a = generate_finding_id("semantic_cross_table", "accuracy", "a->b", [3, 1], ["fk_col"])
    b = generate_finding_id("semantic_cross_table", "accuracy", "a->b", [1, 3], ["fk_col"])
    assert a == b


def test_hash_differs_on_different_inputs():
    a = generate_finding_id("deterministic", "validity", "leads", [3], ["email"])
    b = generate_finding_id("deterministic", "validity", "leads", [4], ["email"])
    assert a != b


def test_hash_handles_dataset_level_finding_with_no_rows_or_fields():
    a = generate_finding_id("deterministic", "consistency", "leads", None, None)
    b = generate_finding_id("deterministic", "consistency", "leads", [], [])
    assert a == b  # None and [] both mean "no scope" -> same sentinel


# --- findings_from_check_result --------------------------------------------

def test_one_finding_per_flagged_row_not_per_check():
    check_result = CheckResult(
        check_name="null_check",
        metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[1, 4],
        total_rows_evaluated=10,
        detail="2 rows missing required fields",
        flagged_fields={1: ["email"], 4: ["phone"]},
    )
    findings = findings_from_check_result(check_result, "leads", {"email": False, "phone": True})
    assert len(findings) == 2
    assert {f.affected_rows[0] for f in findings} == {1, 4}
    assert all(f.check_type == CheckType.DETERMINISTIC for f in findings)
    assert all(f.confidence == 1.0 for f in findings)
    assert all(f.verification_status is None for f in findings)


def test_required_field_gets_higher_severity_than_optional():
    check_result = CheckResult(
        check_name="null_check", metric=MetricCategory.COMPLETENESS,
        flagged_row_indices=[0, 1], total_rows_evaluated=2,
        detail="d", flagged_fields={0: ["required_field"], 1: ["optional_field"]},
    )
    findings = findings_from_check_result(
        check_result, "t", {"required_field": False, "optional_field": True}
    )
    by_row = {f.affected_rows[0]: f for f in findings}
    assert by_row[0].severity == Severity.HIGH
    assert by_row[1].severity == Severity.MEDIUM


def test_check_without_field_attribution_still_produces_a_finding():
    check_result = CheckResult(
        check_name="duplicate_check", metric=MetricCategory.UNIQUENESS,
        flagged_row_indices=[2], total_rows_evaluated=5, detail="d", flagged_fields={},
    )
    findings = findings_from_check_result(check_result, "t", {})
    assert len(findings) == 1
    assert findings[0].affected_fields == []
    assert findings[0].severity == Severity.MEDIUM


# --- findings_from_semantic_flags -------------------------------------------

def test_rejected_semantic_flag_produces_no_finding():
    flags = [_FakeSemanticFlag(0, "looks off", 0.9)]
    verified_by_row = {0: _FakeVerifiedFlag(0, _FakeLabel("rejected"))}
    findings = findings_from_semantic_flags(flags, verified_by_row, "leads")
    assert findings == []


def test_confirmed_semantic_flag_gets_verification_status_and_high_severity():
    flags = [_FakeSemanticFlag(0, "mismatch", 0.9)]
    verified_by_row = {0: _FakeVerifiedFlag(0, _FakeLabel("confirmed"), "clearly wrong")}
    findings = findings_from_semantic_flags(flags, verified_by_row, "leads")
    assert len(findings) == 1
    assert findings[0].verification_status == VerificationStatus.CONFIRMED
    assert findings[0].severity == Severity.HIGH
    assert findings[0].metadata["verifier_notes"] == "clearly wrong"


def test_unverified_semantic_flag_has_none_status():
    flags = [_FakeSemanticFlag(0, "mismatch", 0.6)]
    findings = findings_from_semantic_flags(flags, {}, "leads")
    assert len(findings) == 1
    assert findings[0].verification_status is None


# --- findings_from_cross_table_semantic -------------------------------------

def test_cross_table_finding_folds_both_rows_and_tables_into_one_finding():
    ctf = _FakeCrossTableFinding(
        "contacts", 1, "accounts", 1, "account_id", "company mismatch", 0.9,
        verification_label="confirmed", verification_notes="names differ",
    )
    findings = findings_from_cross_table_semantic([ctf])
    assert len(findings) == 1
    f = findings[0]
    assert f.affected_dataset == "contacts->accounts"
    assert set(f.affected_rows) == {1, 1}
    assert f.affected_fields == ["account_id"]
    assert f.check_type == CheckType.SEMANTIC_CROSS_TABLE
    assert f.verification_status == VerificationStatus.CONFIRMED


def test_cross_table_finding_id_is_order_independent_for_row_pair():
    ctf_a = _FakeCrossTableFinding("contacts", 0, "accounts", 5, "account_id", "r", 0.9)
    ctf_b = _FakeCrossTableFinding("contacts", 5, "accounts", 0, "account_id", "r", 0.9)
    id_a = findings_from_cross_table_semantic([ctf_a])[0].id
    id_b = findings_from_cross_table_semantic([ctf_b])[0].id
    assert id_a == id_b


# --- calibrated_confidence is populated, independently of `confidence` -----

def test_deterministic_finding_calibrated_confidence_is_full():
    check_result = CheckResult(
        check_name="duplicate_check", metric=MetricCategory.UNIQUENESS,
        flagged_row_indices=[0], total_rows_evaluated=1, detail="d", flagged_fields={},
    )
    finding = findings_from_check_result(check_result, "t", {})[0]
    assert finding.calibrated_confidence == 1.0


def test_confirmed_semantic_finding_calibrated_confidence_ignores_raw_confidence():
    """The generator's raw confidence (0.5 here) shouldn't drive the
    calibrated figure at all — a genuine CONFIRMED from the verifier is
    what raises it, per app/domain/calibration.py."""
    flags = [_FakeSemanticFlag(0, "mismatch", 0.5)]
    verified_by_row = {0: _FakeVerifiedFlag(0, _FakeLabel("confirmed"))}
    finding = findings_from_semantic_flags(flags, verified_by_row, "leads")[0]
    assert finding.calibrated_confidence > 0.5  # calibration overrode the low raw confidence


def test_technical_verification_failure_lowers_calibrated_confidence_vs_unverified():
    class _FakeFailedVerifiedFlag(_FakeVerifiedFlag):
        def __init__(self, row_index, label):
            super().__init__(row_index, label)
            self.verification_failed = True

    flags = [_FakeSemanticFlag(0, "mismatch", 0.9)]
    unverified = findings_from_semantic_flags(flags, {}, "leads")[0]
    failed = findings_from_semantic_flags(
        flags, {0: _FakeFailedVerifiedFlag(0, _FakeLabel("needs_review"))}, "leads"
    )[0]
    assert failed.calibrated_confidence < unverified.calibrated_confidence


def test_cross_table_finding_calibrated_confidence_starts_lower_than_single_table():
    ctf = _FakeCrossTableFinding("contacts", 0, "accounts", 5, "account_id", "r", 0.9)
    cross_table = findings_from_cross_table_semantic([ctf])[0]

    flags = [_FakeSemanticFlag(0, "r", 0.9)]
    single_table = findings_from_semantic_flags(flags, {}, "leads")[0]

    assert cross_table.calibrated_confidence < single_table.calibrated_confidence
