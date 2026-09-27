from __future__ import annotations

import re
from collections import defaultdict

from app.canonical.models import CanonicalTable, ScanContext
from app.checks.base import Check, CheckResult, MetricCategory, register

# Same "hints over hardcoding" pattern this codebase already uses
# elsewhere (CSVConnector._infer_semantic_hint tags a column "email" by
# name substring, not a fixed literal field list; ReferentialIntegrityCheck
# does the same with the "_id" suffix) — applied here to identify which
# columns represent entity identity, rather than a fixed list of exact
# CRM field names. A column only needs to MATCH one of these common
# names, not be named exactly this; see _name_and_company_columns.
_NAME_COLUMN_NAMES = {"name", "full_name", "contact_name", "customer_name"}
_COMPANY_COLUMN_NAMES = {"company", "company_name", "account_name", "organization", "org"}


def _normalize(value: object) -> str:
    """Lowercase, strip, and collapse internal whitespace runs to one
    space — case differences and stray/doubled whitespace shouldn't
    hide a genuine duplicate. Deliberately NOT fuzzy/typo-tolerant
    matching (edit-distance, phonetic matching): that needs a
    similarity threshold tuned against real labeled data, a bigger,
    separate piece of work than this normalization pass."""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _email_column(table: CanonicalTable) -> str | None:
    return next((c.name for c in table.columns if c.semantic_hint == "email"), None)


def _name_and_company_columns(table: CanonicalTable) -> tuple[str | None, str | None]:
    """Requires BOTH a name-like and a company-like column — name alone
    is deliberately not treated as a business key, since two different
    real people/accounts can legitimately share a name. This mirrors
    the actual review guidance this check was built from: 'same email,
    same normalized name plus company', not name alone."""
    names_by_lower = {c.name.lower(): c.name for c in table.columns}
    company_col = next((names_by_lower[n] for n in _COMPANY_COLUMN_NAMES if n in names_by_lower), None)
    name_col = next((names_by_lower[n] for n in _NAME_COLUMN_NAMES if n in names_by_lower), None)
    return name_col, company_col


@register
class DuplicateCheck(Check):
    """Flags rows that share a real-world identity with another row,
    not just rows that are byte-identical across every column.

    Reproduced bug this fixes: the original version matched on the
    ENTIRE row, including the primary `id` — so two rows describing the
    same person/account with two different IDs (the actual, common
    shape of a CRM duplicate) were completely invisible to it. A probe
    table with 30 rows of one duplicated person under 30 different IDs
    scored uniqueness=100.0, a perfect score, on data that was 30%
    duplicate.

    Detection now runs on the table's real-world identity, in order of
    how strong a signal it is:
    1. A column hinted as `email` (see CSVConnector._infer_semantic_hint)
       — matched after normalization (case/whitespace), since email is
       the single most reliable stable identity signal typically
       present in this kind of data.
    2. A name-like column PAIRED WITH a company-like column (see
       _name_and_company_columns) — matched on the normalized
       composite. Name alone is deliberately not used as a key.
    Both signals run independently and their results are unioned when
    both are present — every real signal this table offers gets used,
    not just the strongest one. Rows where a key's own value is blank
    are never compared on that key (a shared blank is not a shared
    identity).

    If NEITHER signal is available on this table's schema, this falls
    back to the original exact-full-row match — so a table that
    doesn't match either identity pattern is never LESS covered than
    it was before this fix, even though it also can't yet benefit from
    business-key matching. flagged_fields is deliberately left empty in
    every path (same as before this fix): duplication is a whole-row
    property, not one field's fault, regardless of which signal caught
    it — this check's weight in the scorer stays the flat, unattributed
    default on purpose.

    Still a known, honest limitation: exact-match-after-normalization,
    not fuzzy/typo-tolerant matching (see _normalize's docstring) —
    'Jon Smith' at 'Acme Corp' vs 'Jonathan Smith' at 'Acme Corporation'
    still won't be caught here. That's real future work, not something
    this pass claims to have solved.
    """

    name = "duplicate_check"
    metric = MetricCategory.UNIQUENESS

    def applies_to(self, table: CanonicalTable, context: ScanContext | None = None) -> bool:
        return len(table.rows) > 1

    def _business_keys(self, table: CanonicalTable) -> list[tuple[str, object]]:
        """Returns (label, key_fn) pairs — key_fn(row) -> normalized
        composite key string, or None when this row has nothing
        comparable for that key (a blank component)."""
        keys: list[tuple[str, object]] = []

        email_col = _email_column(table)
        if email_col:
            def email_key(row: dict, col: str = email_col) -> str | None:
                v = row.get(col)
                return None if v in (None, "") else _normalize(v)

            keys.append(("email", email_key))

        name_col, company_col = _name_and_company_columns(table)
        if name_col and company_col:
            def name_company_key(row: dict, nc: str = name_col, cc: str = company_col) -> str | None:
                nv, cv = row.get(nc), row.get(cc)
                if nv in (None, "") or cv in (None, ""):
                    return None
                return f"{_normalize(nv)}|{_normalize(cv)}"

            keys.append(("name+company", name_company_key))

        return keys

    def run(self, table: CanonicalTable, context: ScanContext | None = None) -> CheckResult:
        business_keys = self._business_keys(table)
        flagged: set[int] = set()
        notes: list[str] = []

        if business_keys:
            for label, key_fn in business_keys:
                groups: dict[str, list[int]] = defaultdict(list)
                for i, row in enumerate(table.rows):
                    k = key_fn(row)
                    if k is None:
                        continue  # a shared blank is not a shared identity
                    groups[k].append(i)
                dup_rows = [i for indices in groups.values() if len(indices) > 1 for i in indices]
                if dup_rows:
                    notes.append(f"{label}: {len(dup_rows)} rows share a business key with another row")
                    flagged.update(dup_rows)
        else:
            # Fallback — neither identity signal is available on this
            # schema. Same exact-full-row match as before this fix, so
            # this table is never LESS covered than it used to be.
            groups: dict[tuple, list[int]] = defaultdict(list)
            for i, row in enumerate(table.rows):
                key = tuple(sorted((k, str(v)) for k, v in row.items()))
                groups[key].append(i)
            dup_rows = [i for indices in groups.values() if len(indices) > 1 for i in indices]
            if dup_rows:
                notes.append(f"exact row match: {len(dup_rows)} rows are byte-identical to another row")
                flagged.update(dup_rows)

        return CheckResult(
            check_name=self.name,
            metric=self.metric,
            flagged_row_indices=sorted(flagged),
            total_rows_evaluated=len(table.rows),
            detail="; ".join(notes) if notes else "no duplicates found",
        )
