from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.checks.uniqueness import DuplicateCheck


def _table(rows: list[dict], columns: list[ColumnSchema] | None = None) -> CanonicalTable:
    cols = columns or [
        ColumnSchema(name="email", type=ColumnType.STRING, nullable=False),
        ColumnSchema(name="amount", type=ColumnType.INTEGER, nullable=False),
    ]
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="leads",
        columns=cols,
        rows=rows,
    )


def test_does_not_apply_to_single_row_table():
    table = _table([{"email": "a@example.com", "amount": 100}])
    assert DuplicateCheck().applies_to(table) is False


# --- Fallback path: no email hint, no name+company pair -----------------
# (the _table() helper's default schema has no semantic_hint set, so
# these exercise the original exact-full-row behavior unchanged.)

def test_fallback_flags_exact_duplicate_rows():
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


def test_fallback_no_false_positive_on_similar_but_different_rows():
    table = _table(
        [
            {"email": "a@example.com", "amount": 100},
            {"email": "a@example.com", "amount": 200},  # same email, different amount
        ]
    )
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == []


# --- Business-key path: email hint --------------------------------------

def _email_hinted_table(rows: list[dict]) -> CanonicalTable:
    return _table(
        rows,
        columns=[
            ColumnSchema(name="id", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False, semantic_hint="email"),
            ColumnSchema(name="amount", type=ColumnType.INTEGER, nullable=True),
        ],
    )


def test_reproduced_bug_catches_business_key_duplicates_with_different_ids():
    """The exact case this fix was written for: 30 rows describing the
    same person under 30 DIFFERENT ids — invisible to the original
    exact-full-row match, caught here via the normalized email."""
    rows = [{"id": i, "email": f"user{i}@x.com", "amount": 10} for i in range(70)]
    rows += [{"id": 1000 + i, "email": "dup@x.com", "amount": 20} for i in range(30)]
    table = _email_hinted_table(rows)

    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == list(range(70, 100))
    assert result.flagged_fields == {}  # still whole-row, unattributed — see docstring


def test_email_matching_is_case_and_whitespace_normalized():
    rows = [
        {"id": 1, "email": "A@Example.com", "amount": 10},
        {"id": 2, "email": " a@example.com ", "amount": 20},
        {"id": 3, "email": "b@example.com", "amount": 30},
    ]
    table = _email_hinted_table(rows)
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == [0, 1]


def test_blank_email_never_counts_as_a_shared_key():
    rows = [
        {"id": 1, "email": "", "amount": 10},
        {"id": 2, "email": "", "amount": 20},
        {"id": 3, "email": "b@example.com", "amount": 30},
    ]
    table = _email_hinted_table(rows)
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == []


# --- Business-key path: name + company ----------------------------------

def _name_company_table(rows: list[dict]) -> CanonicalTable:
    return _table(
        rows,
        columns=[
            ColumnSchema(name="id", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="name", type=ColumnType.STRING, nullable=True),
            ColumnSchema(name="company", type=ColumnType.STRING, nullable=True),
        ],
    )


def test_name_alone_is_not_a_business_key_without_company():
    """Two different real people can share a name — requires the
    company pairing before it's treated as an identity match."""
    table = _table(
        [
            {"id": 1, "name": "John Smith", "amount": 10},
            {"id": 2, "name": "John Smith", "amount": 20},  # same name, no company column at all
        ],
        columns=[
            ColumnSchema(name="id", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="name", type=ColumnType.STRING, nullable=True),
            ColumnSchema(name="amount", type=ColumnType.INTEGER, nullable=True),
        ],
    )
    # No email hint, no company column -> falls back to exact-full-row,
    # and these two rows differ on "amount", so neither is flagged.
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == []


def test_name_plus_company_composite_catches_duplicates_under_different_ids():
    rows = [
        {"id": 1, "name": "Jane Doe", "company": "Acme Corp"},
        {"id": 2, "name": "jane doe", "company": "  acme corp  "},  # same identity, normalized
        {"id": 3, "name": "Jane Doe", "company": "Globex"},  # same name, different company -> not a dup
    ]
    table = _name_company_table(rows)
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == [0, 1]


def test_both_signals_run_when_both_are_present():
    """A table with both an email hint AND a name+company pair should
    catch duplicates matched by EITHER signal, not just the strongest
    one."""
    rows = [
        {"id": 1, "email": "a@x.com", "name": "Jane Doe", "company": "Acme"},
        {"id": 2, "email": "a@x.com", "name": "Someone Else", "company": "Other"},  # email match only
        {"id": 3, "email": "b@x.com", "name": "Jane Doe", "company": "Acme"},  # name+company match only
    ]
    table = _table(
        rows,
        columns=[
            ColumnSchema(name="id", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="email", type=ColumnType.STRING, nullable=False, semantic_hint="email"),
            ColumnSchema(name="name", type=ColumnType.STRING, nullable=True),
            ColumnSchema(name="company", type=ColumnType.STRING, nullable=True),
        ],
    )
    result = DuplicateCheck().run(table)
    assert result.flagged_row_indices == [0, 1, 2]
