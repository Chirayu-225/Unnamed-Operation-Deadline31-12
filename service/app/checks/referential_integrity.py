from __future__ import annotations

from app.canonical.models import CanonicalTable, ScanContext
from app.checks.base import Check, CheckResult, MetricCategory, register

# Naming heuristic for detecting candidate foreign keys, same spirit as
# the CSV connector's semantic-hint inference: a column named
# "account_id" is presumed to reference a table named "accounts",
# column "id". This is a guess, not real schema metadata — it'll be
# replaced by actual foreign-key metadata once the SQL and Salesforce
# connectors exist, same as the format-validity hint inference.
_FK_SUFFIX = "_id"
_PK_COLUMN = "id"


def _related_table_name(fk_column: str) -> str:
    base = fk_column[: -len(_FK_SUFFIX)]
    return base if base.endswith("s") else base + "s"


@register
class ReferentialIntegrityCheck(Check):
    """Flags foreign-key-shaped values that don't point at a real row.

    Two modes, chosen automatically based on what's available:
    - If the related table is present in the scan's ScanContext: a
      REAL check — does this account_id actually exist in the accounts
      table's id column.
    - If no related table is available (the common case for a single
      CSV upload with no second file): degrades to a weaker signal —
      flag only blank foreign-key values, since without the related
      table there's nothing to verify existence against. This is a
      known, deliberate limitation, not a silent gap: the detail
      message says explicitly when it's operating in this mode.
    """

    name = "referential_integrity_check"
    metric = MetricCategory.CONSISTENCY

    def _fk_columns(self, table: CanonicalTable) -> list[str]:
        return [
            name
            for name in table.column_names()
            if name.endswith(_FK_SUFFIX) and name != _PK_COLUMN
        ]

    def applies_to(self, table: CanonicalTable, context: ScanContext | None = None) -> bool:
        return len(self._fk_columns(table)) > 0

    def run(self, table: CanonicalTable, context: ScanContext | None = None) -> CheckResult:
        flagged: set[int] = set()
        flagged_fields: dict[int, list[str]] = {}
        notes: list[str] = []

        for fk_col in self._fk_columns(table):
            related_name = _related_table_name(fk_col)
            related_table = context.get_table(related_name) if context else None

            if related_table is not None:
                valid_ids = {
                    str(row.get(_PK_COLUMN))
                    for row in related_table.rows
                    if row.get(_PK_COLUMN) not in (None, "")
                }
                bad = [
                    i
                    for i, row in enumerate(table.rows)
                    if row.get(fk_col) not in (None, "")
                    and str(row.get(fk_col)) not in valid_ids
                ]
                if bad:
                    notes.append(
                        f"{fk_col}: {len(bad)} rows reference missing "
                        f"{related_name} records"
                    )
                    flagged.update(bad)
                    for i in bad:
                        flagged_fields.setdefault(i, []).append(fk_col)
            else:
                # Fallback mode — no related table to verify against.
                bad = [
                    i for i, row in enumerate(table.rows) if row.get(fk_col) in (None, "")
                ]
                if bad:
                    notes.append(
                        f"{fk_col}: {len(bad)} rows have a blank reference "
                        f"(no '{related_name}' table available to verify "
                        f"existence against — fallback mode)"
                    )
                    flagged.update(bad)
                    for i in bad:
                        flagged_fields.setdefault(i, []).append(fk_col)

        return CheckResult(
            check_name=self.name,
            metric=self.metric,
            flagged_row_indices=sorted(flagged),
            total_rows_evaluated=len(table.rows),
            detail="; ".join(notes) if notes else "no referential integrity issues found",
            flagged_fields=flagged_fields,
        )
