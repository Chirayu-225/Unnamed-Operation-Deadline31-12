from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType, ScanContext
from app.checks.referential_integrity import ReferentialIntegrityCheck


def _leads_table(rows: list[dict]) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING),
            ColumnSchema(name="account_id", type=ColumnType.INTEGER),
        ],
        rows=rows,
    )


def _accounts_table(ids: list[int]) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="accounts",
        columns=[ColumnSchema(name="id", type=ColumnType.INTEGER)],
        rows=[{"id": i} for i in ids],
    )


def test_real_mode_flags_fk_with_no_matching_parent_row():
    leads = _leads_table(
        [
            {"email": "a@example.com", "account_id": 1},
            {"email": "b@example.com", "account_id": 99},  # doesn't exist
        ]
    )
    accounts = _accounts_table([1, 2, 3])
    context = ScanContext(tables=[leads, accounts])

    result = ReferentialIntegrityCheck().run(leads, context)
    assert result.flagged_row_indices == [1]
    assert "missing accounts records" in result.detail


def test_real_mode_does_not_flag_valid_references():
    leads = _leads_table(
        [
            {"email": "a@example.com", "account_id": 1},
            {"email": "b@example.com", "account_id": 2},
        ]
    )
    accounts = _accounts_table([1, 2, 3])
    context = ScanContext(tables=[leads, accounts])

    result = ReferentialIntegrityCheck().run(leads, context)
    assert result.flagged_row_indices == []


def test_fallback_mode_flags_only_blanks_when_no_related_table():
    leads = _leads_table(
        [
            {"email": "a@example.com", "account_id": 1},
            {"email": "b@example.com", "account_id": ""},  # blank -> flagged
            {"email": "c@example.com", "account_id": 999},  # unverifiable, not flagged
        ]
    )
    # No context at all — simulates a lone CSV upload with no second file
    result = ReferentialIntegrityCheck().run(leads, context=None)
    assert result.flagged_row_indices == [1]
    assert "fallback mode" in result.detail


def test_applies_to_detects_fk_shaped_columns():
    leads = _leads_table([{"email": "a@example.com", "account_id": 1}])
    assert ReferentialIntegrityCheck().applies_to(leads) is True

    no_fk = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING)],
        rows=[{"email": "a@example.com"}],
    )
    assert ReferentialIntegrityCheck().applies_to(no_fk) is False


def test_field_attribution_in_real_mode():
    leads = _leads_table(
        [
            {"email": "a@example.com", "account_id": 1},
            {"email": "b@example.com", "account_id": 99},
        ]
    )
    accounts = _accounts_table([1, 2, 3])
    context = ScanContext(tables=[leads, accounts])

    result = ReferentialIntegrityCheck().run(leads, context)
    assert result.flagged_fields[1] == ["account_id"]


def test_field_attribution_in_fallback_mode():
    leads = _leads_table([{"email": "a@example.com", "account_id": ""}])
    result = ReferentialIntegrityCheck().run(leads, context=None)
    assert result.flagged_fields[0] == ["account_id"]
