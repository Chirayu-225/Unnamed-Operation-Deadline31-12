"""
Deterministic check registry.

Each check is independent and composable: it takes a CanonicalTable and
returns flagged rows + a metric contribution. New checks register
themselves without touching existing ones — this is what the agent's
"tool execution" step actually calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel

from app.canonical.models import CanonicalTable, ScanContext


class MetricCategory(str, Enum):
    """The 5 scorecard metrics every check must declare itself under."""

    COMPLETENESS = "completeness"
    UNIQUENESS = "uniqueness"
    VALIDITY = "validity"
    CONSISTENCY = "consistency"
    ACCURACY = "accuracy"


class CheckResult(BaseModel):
    check_name: str
    metric: MetricCategory
    flagged_row_indices: list[int]
    total_rows_evaluated: int
    detail: str
    # Optional field-level attribution: row_index -> which specific
    # column(s) caused that row to be flagged. Backward compatible —
    # defaults to empty, and checks where "which field" doesn't really
    # apply (DuplicateCheck: duplication is a whole-row property, not
    # one field's fault) simply leave it empty. This is what lets the
    # scorer weight a flag on a required field more heavily than one
    # on an optional field, instead of treating every flagged row
    # identically regardless of which column caused it.
    flagged_fields: dict[int, list[str]] = {}


class Check(ABC):
    """Base class for a deterministic check."""

    name: str
    metric: MetricCategory

    @abstractmethod
    def applies_to(self, table: CanonicalTable, context: ScanContext | None = None) -> bool:
        """Whether this check is relevant given the table's schema
        (e.g. a format-validity check for emails only applies to
        columns hinted as `email`). `context` is only needed by checks
        that look across tables (referential integrity); most checks
        ignore it."""
        raise NotImplementedError

    @abstractmethod
    def run(self, table: CanonicalTable, context: ScanContext | None = None) -> CheckResult:
        raise NotImplementedError


_REGISTRY: list[type[Check]] = []


def register(check_cls: type[Check]) -> type[Check]:
    """Decorator: adding a new check is just `@register` on the class —
    nothing else in the system needs to change."""
    _REGISTRY.append(check_cls)
    return check_cls


def all_checks() -> list[type[Check]]:
    return list(_REGISTRY)
