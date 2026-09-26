from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType


def test_canonical_table_requires_tenant_and_source():
    table = CanonicalTable(
        tenant_id="tenant-1",
        source_id="csv-connector-1",
        table_name="leads",
        columns=[ColumnSchema(name="email", type=ColumnType.STRING, nullable=False)],
        rows=[{"email": "a@example.com"}],
    )
    assert table.tenant_id == "tenant-1"
    assert table.column_names() == {"email"}


def test_column_names_matches_declared_columns():
    table = CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="x",
        columns=[
            ColumnSchema(name="id", type=ColumnType.INTEGER, nullable=False),
            ColumnSchema(name="name", type=ColumnType.STRING),
        ],
        rows=[],
    )
    assert table.column_names() == {"id", "name"}
