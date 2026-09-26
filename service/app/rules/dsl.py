"""
Rule DSL.

Deliberately data, never code. A compiled rule is inspectable, storable,
diffable against schema changes, and safe to execute automatically
because its operator set is closed. Logic too complex to express here
(rolling averages, per-group comparisons) is marked `is_computed` and
routed to the sandboxed execution engine instead of stretching this
format to breaking point.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Operator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    MATCHES_PATTERN = "matches_pattern"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    IN_SET = "in_set"


class Conjunction(str, Enum):
    AND = "and"
    OR = "or"


class RuleCondition(BaseModel):
    field: str
    operator: Operator
    # A literal value, OR a reference to another canonical field name
    # (cross-field rules like "amount negative AND refund_flag false").
    value: str | int | float | bool | list[str] | None = None
    value_is_field_ref: bool = False


class RuleSource(str, Enum):
    USER_AUTHORED = "user_authored"
    AGENT_INFERRED = "agent_inferred"


class CompiledRule(BaseModel):
    """The compiler's output — what the deterministic engine actually
    executes, or what gets shown back to the user for confirmation."""

    version: int = 1
    conditions: list[RuleCondition]
    conjunction: Conjunction = Conjunction.AND
    is_computed: bool = False  # True -> route to sandboxed execution instead
    source: RuleSource
    # Auto-generated from the structured form — this is what powers the
    # "here's what I understood, run this?" confirmation step.
    human_readable_description: str
