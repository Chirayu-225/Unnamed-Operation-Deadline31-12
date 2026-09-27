from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.checks.completeness import NullCheck


def test_null_check_flags_missing_required_field():
    """Required-field blanks are flagged (row 1: email). Optional-field
    blanks are now ALSO flagged (rows 0 and 2: notes) rather than
    invisible to this check — see NullCheck's docstring for the
    reproduced circularity bug this fixes (nullable itself is inferred
    from a column's own blank ratio, so gating this check on nullable
    meant a column could excuse itself from completeness scoring by
    being blank often enough). Severity is still distinguished
    downstream by field-criticality weight, not by one tier being
    invisible here."""
    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),
            ColumnSchema(name="notes", type=ColumnType.STRING, nullable=True),
        ],
        rows=[
            {"email": "a@example.com", "notes": ""},
            {"email": "", "notes": "vip"},
            {"email": "b@example.com", "notes": None},
        ],
    )
    check = NullCheck()
    assert check.applies_to(table) is True

    result = check.run(table)
    assert result.flagged_row_indices == [0, 1, 2]
    assert result.flagged_fields[0] == ["notes"]
    assert result.flagged_fields[1] == ["email"]
    assert result.flagged_fields[2] == ["notes"]
    assert result.total_rows_evaluated == 3


def test_null_check_field_attribution_identifies_correct_column():
    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),
            ColumnSchema(name="phone", type=ColumnType.STRING, nullable=False),
        ],
        rows=[
            {"email": "a@example.com", "phone": "555-1234"},  # clean
            {"email": "", "phone": "555-5678"},  # email missing only
            {"email": "", "phone": ""},  # both missing
        ],
    )
    result = NullCheck().run(table)
    assert result.flagged_row_indices == [1, 2]
    assert result.flagged_fields[1] == ["email"]
    assert set(result.flagged_fields[2]) == {"email", "phone"}
    assert 0 not in result.flagged_fields  # clean row has no attribution at all
