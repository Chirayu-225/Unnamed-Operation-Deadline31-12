from __future__ import annotations

import csv
from pathlib import Path

from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.connectors.base import Connector


def _infer_semantic_hint(column_name: str) -> str | None:
    """CSV has no native field-type metadata, unlike Salesforce or a SQL
    schema, so we fall back to a simple name-based heuristic. This is
    intentionally permissive/best-effort — a wrong guess here only
    means a format check runs (or doesn't run) on a field, not that
    data gets mis-flagged, since the checks themselves stay permissive
    too. A richer connector (Salesforce field types) should set this
    from real metadata instead of guessing from the name."""
    name = column_name.lower()
    if "email" in name:
        return "email"
    if "phone" in name:
        return "phone"
    if "date" in name:
        return "date"
    return None


def _blank_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    blanks = sum(1 for v in values if v in ("", None))
    return blanks / len(values)


def _infer_type(values: list[str]) -> ColumnType:
    """Best-effort type inference from a column's raw string values.
    Intentionally simple for the skeleton — this is a good spot to
    harden later (dates, currency formats, etc.) without touching
    anything else in the connector."""
    sample = [v for v in values if v not in ("", None)][:50]
    if not sample:
        return ColumnType.UNKNOWN
    if all(v.lower() in ("true", "false") for v in sample):
        return ColumnType.BOOLEAN
    try:
        [int(v) for v in sample]
        return ColumnType.INTEGER
    except ValueError:
        pass
    try:
        [float(v) for v in sample]
        return ColumnType.FLOAT
    except ValueError:
        pass
    return ColumnType.STRING


class CSVConnector(Connector):
    """Reads a local CSV file and normalizes it into a CanonicalTable.
    `settings["file_path"]` is required in the connector config."""

    def test_connection(self) -> bool:
        path = Path(self.config.settings.get("file_path", ""))
        return path.is_file()

    def extract(self) -> list[CanonicalTable]:
        path = Path(self.config.settings["file_path"])
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        columns_raw: dict[str, list[str]] = {name: [] for name in fieldnames}
        for row in rows:
            for name in fieldnames:
                columns_raw[name].append(row.get(name, ""))

        columns = [
            ColumnSchema(
                name=name,
                type=_infer_type(values),
                # Heuristic, not a certainty: a column blank in a small
                # minority of rows looks like *missing required data*
                # (flag it). A column blank in most rows looks like a
                # genuinely optional field (don't flag it). This will
                # get real refinement later (e.g. semantic hints like
                # "email" implying required), but it's a meaningfully
                # better default than "any blank -> nullable", which
                # excused every partially-missing required field from
                # the completeness check entirely.
                nullable=_blank_ratio(values) >= 0.5,
                semantic_hint=_infer_semantic_hint(name),
            )
            for name, values in columns_raw.items()
        ]

        table = CanonicalTable(
            tenant_id=self.config.tenant_id,
            source_id=self.config.source_id,
            table_name=path.stem,
            columns=columns,
            rows=[dict(row) for row in rows],
        )
        return [table]
