from __future__ import annotations

from app.canonical.models import CanonicalTable, ScanContext
from app.checks.base import Check, CheckResult, MetricCategory, register


@register
class NullCheck(Check):
    """Flags rows with a null/blank value in a non-nullable column.
    Deliberately simple — this is the reference implementation new
    checks should follow, not the final word on completeness."""

    name = "null_check"
    metric = MetricCategory.COMPLETENESS

    def applies_to(self, table: CanonicalTable, context: ScanContext | None = None) -> bool:
        return any(not c.nullable for c in table.columns)

    def run(self, table: CanonicalTable, context: ScanContext | None = None) -> CheckResult:
        required_cols = [c.name for c in table.columns if not c.nullable]
        flagged: list[int] = []
        flagged_fields: dict[int, list[str]] = {}
        for i, row in enumerate(table.rows):
            blank = [col for col in required_cols if row.get(col) in (None, "")]
            if blank:
                flagged.append(i)
                flagged_fields[i] = blank
        return CheckResult(
            check_name=self.name,
            metric=self.metric,
            flagged_row_indices=flagged,
            total_rows_evaluated=len(table.rows),
            detail=f"{len(flagged)} rows missing a required field",
            flagged_fields=flagged_fields,
        )
