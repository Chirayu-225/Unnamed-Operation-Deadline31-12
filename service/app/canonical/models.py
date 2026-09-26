"""
Canonical data model.

This is the internal "lingua franca" every connector must translate its
source into. Nothing downstream of this module (checks, agent, scoring)
is allowed to know or care where the data originally came from. If a
field like `salesforce_object_type` ever shows up here, the connector
abstraction has leaked — that's a design smell to catch in review.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ColumnType(str, Enum):
    """Closed set of canonical types. Every connector maps its native
    types down to one of these — this is what keeps checks and the
    rule DSL source-agnostic."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    UNKNOWN = "unknown"


class ColumnSchema(BaseModel):
    """Describes one column/field in a canonical table."""

    name: str
    type: ColumnType
    nullable: bool = True
    # Optional hint set by a connector or inferred later (e.g. "email",
    # "phone", "currency"). Used by checks to pick relevant validations
    # without hardcoding source-specific field names.
    semantic_hint: str | None = None


class CanonicalTable(BaseModel):
    """A single table/object, normalized to the canonical shape.

    `tenant_id` and `source_id` are required on every table so
    multi-tenancy and provenance are threaded through from the very
    first connector call, not bolted on later.
    """

    tenant_id: str
    source_id: str  # which connector instance this came from
    table_name: str
    columns: list[ColumnSchema]
    rows: list[dict[str, Any]]

    def column_names(self) -> set[str]:
        return {c.name for c in self.columns}


class ScanContext(BaseModel):
    """Bundles every table extracted in one scan. Most checks only ever
    look at a single table and can ignore this entirely — it exists
    for checks that inherently need to see across tables, like
    referential integrity (does this foreign key actually point at a
    real row somewhere else). A lone CSV upload will usually produce a
    context with just one table; a SQL connector or a multi-file scan
    can produce several."""

    tables: list[CanonicalTable]

    def get_table(self, name: str) -> CanonicalTable | None:
        for t in self.tables:
            if t.table_name == name:
                return t
        return None
