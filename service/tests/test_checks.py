from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.checks.completeness import NullCheck


def test_null_check_flags_missing_required_field():
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
    assert result.flagged_row_indices == [1]
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
