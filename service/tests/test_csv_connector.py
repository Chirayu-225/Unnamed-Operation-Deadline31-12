import csv
from pathlib import Path

from app.connectors.base import ConnectorConfig
from app.connectors.csv_connector import CSVConnector


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "leads.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "amount"])
        writer.writerow(["a@example.com", "100"])
        writer.writerow(["", "-50"])  # missing email -> should flag as nullable
        writer.writerow(["b@example.com", "75"])
    return path


def test_csv_connector_extracts_canonical_table(tmp_path):
    path = _write_fixture(tmp_path)
    config = ConnectorConfig(
        tenant_id="tenant-1", source_id="csv-1", settings={"file_path": str(path)}
    )
    connector = CSVConnector(config)

    assert connector.test_connection() is True

    tables = connector.extract()
    assert len(tables) == 1
    table = tables[0]
    assert table.tenant_id == "tenant-1"
    assert table.column_names() == {"email", "amount"}
    assert len(table.rows) == 3


def test_csv_connector_test_connection_fails_on_missing_file():
    config = ConnectorConfig(
        tenant_id="t", source_id="s", settings={"file_path": "/no/such/file.csv"}
    )
    connector = CSVConnector(config)
    assert connector.test_connection() is False


def test_nullability_inferred_from_blank_ratio(tmp_path):
    """A column blank in a small minority of rows should be treated as
    required (nullable=False), not excused from the completeness check
    just because it has *any* blank. A column blank in most rows should
    be treated as genuinely optional."""
    path = tmp_path / "mixed.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "middle_name"])
        # email: blank in 1 of 4 rows (25%) -> should read as required
        writer.writerow(["a@example.com", ""])
        writer.writerow(["b@example.com", "Lee"])
        writer.writerow(["", ""])
        writer.writerow(["c@example.com", ""])
        # middle_name: blank in 3 of 4 rows (75%) -> should read as optional

    config = ConnectorConfig(
        tenant_id="t", source_id="s", settings={"file_path": str(path)}
    )
    table = CSVConnector(config).extract()[0]
    columns_by_name = {c.name: c for c in table.columns}

    assert columns_by_name["email"].nullable is False
    assert columns_by_name["middle_name"].nullable is True
