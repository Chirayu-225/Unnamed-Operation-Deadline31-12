"""
Rule executor.

Runs a CompiledRule against a CanonicalTable's real rows. Deliberately
interprets DATA, never executes generated code — the entire point of
compiling into the DSL instead of letting an LLM write arbitrary logic
was to keep this step safe and predictable. Every operator here is a
small, explicit comparison; there is no eval(), no exec(), nothing
that runs untrusted logic directly.

A malformed comparison (e.g. a greater_than rule against a
non-numeric value) fails that row's condition rather than crashing the
whole scan — consistent with the fail-safe philosophy used everywhere
else in the agent layer.
"""

from __future__ import annotations

import re

from app.canonical.models import CanonicalTable
from app.checks.base import CheckResult, MetricCategory
from app.rules.dsl import CompiledRule, Conjunction, Operator, RuleCondition


def _evaluate_condition(row: dict, condition: RuleCondition) -> bool:
    value = row.get(condition.field)

    if condition.operator == Operator.IS_NULL:
        return value in (None, "")
    if condition.operator == Operator.IS_NOT_NULL:
        return value not in (None, "")

    # Every other operator needs an actual value to compare — a
    # missing/blank field can't satisfy them meaningfully, so treat it
    # as a non-match rather than raising.
    if value in (None, ""):
        return False

    target = condition.value

    try:
        if condition.operator == Operator.EQUALS:
            return str(value) == str(target)
        if condition.operator == Operator.NOT_EQUALS:
            return str(value) != str(target)
        if condition.operator == Operator.GREATER_THAN:
            return float(value) > float(target)
        if condition.operator == Operator.LESS_THAN:
            return float(value) < float(target)
        if condition.operator == Operator.CONTAINS:
            return str(target).lower() in str(value).lower()
        if condition.operator == Operator.MATCHES_PATTERN:
            return bool(re.search(str(target), str(value)))
        if condition.operator == Operator.IN_SET:
            values = target if isinstance(target, list) else [target]
            return str(value) in [str(v) for v in values]
    except (TypeError, ValueError, re.error):
        return False  # malformed comparison -> this row just doesn't match

    return False  # unreachable given the closed Operator enum, but stay safe


def execute_rule(table: CanonicalTable, rule: CompiledRule) -> CheckResult:
    """Evaluate every row against the rule's conditions, combined with
    its conjunction (AND/OR), and return a CheckResult in the same
    shape the deterministic checks produce — so a custom rule's output
    slots into the same aggregation everything else already uses."""
    flagged: list[int] = []
    for i, row in enumerate(table.rows):
        condition_results = [_evaluate_condition(row, cond) for cond in rule.conditions]
        matched = all(condition_results) if rule.conjunction == Conjunction.AND else any(condition_results)
        if matched:
            flagged.append(i)

    return CheckResult(
        check_name="custom_rule",
        # Custom rules are user-defined validity criteria by default —
        # a simplification worth revisiting once Phase 4's metric
        # weighting exists and can be more deliberate about this.
        metric=MetricCategory.VALIDITY,
        flagged_row_indices=flagged,
        total_rows_evaluated=len(table.rows),
        detail=rule.human_readable_description,
    )
