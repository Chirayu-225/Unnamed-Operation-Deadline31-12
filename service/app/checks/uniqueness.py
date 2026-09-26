from __future__ import annotations

from collections import defaultdict

from app.canonical.models import CanonicalTable, ScanContext
from app.checks.base import Check, CheckResult, MetricCategory, register


@register
class DuplicateCheck(Check):
    """Flags rows that are exact duplicates of another row in the same
    table (identical values across every column).

    Known limitation, by design for this first pass: this only catches
    *exact* duplicates. Near-duplicates (typos, case differences, a
    trailing space) won't be caught here — that's intentionally left to
    the LLM semantic reasoning layer in Phase 2, which is much better
    suited to "these two rows are probably the same person" judgment
    calls than a hash comparison is. Deterministic + semantic together
    cover both cases; this check alone is not meant to be the full
    answer to duplicate detection.
    """

    name = "duplicate_check"
    metric = MetricCategory.UNIQUENESS

    def applies_to(self, table: CanonicalTable, context: ScanContext | None = None) -> bool:
        return len(table.rows) > 1

    def run(self, table: CanonicalTable, context: ScanContext | None = None) -> CheckResult:
        groups: dict[tuple, list[int]] = defaultdict(list)
        for i, row in enumerate(table.rows):
            # Order-independent, type-stable key: sort by column name so
            # dict key ordering never affects grouping, and stringify
            # values so e.g. int 5 and "5" don't get treated differently
            # depending on source formatting quirks.
            key = tuple(sorted((k, str(v)) for k, v in row.items()))
            groups[key].append(i)

        flagged = sorted(
            i for indices in groups.values() if len(indices) > 1 for i in indices
        )
        return CheckResult(
            check_name=self.name,
            metric=self.metric,
            flagged_row_indices=flagged,
            total_rows_evaluated=len(table.rows),
            detail=f"{len(flagged)} rows are exact duplicates of another row",
        )
