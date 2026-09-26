from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.checks.uniqueness import DuplicateCheck


def _table(rows: list[dict]) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=[
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),
            ColumnSchema(name="amount", type=ColumnType.INTEGER, nullable=False),
        ],
        rows=rows,
    )


def test_flags_exact_duplicate_rows():
    table = _table(
        [
            {"email": "a@example.com", "amount": 100},
            {"email": "b@example.com", "amount": 50},
            {"email": "a@example.com", "amount": 100},  # exact dup of row 0
        ]
    )
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == [0, 2]
    assert result.total_rows_evaluated == 3


def test_no_false_positive_on_similar_but_different_rows():
    table = _table(
        [
            {"email": "a@example.com", "amount": 100},
            {"email": "a@example.com", "amount": 200},  # same email, different amount
        ]
    )
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == []


def test_does_not_apply_to_single_row_table():
    table = _table([{"email": "a@example.com", "amount": 100}])
    assert DuplicateCheck().applies_to(table) is False
