from app.canonical.models import CanonicalTable, ColumnSchema, ColumnType
from app.rules.dsl import CompiledRule, Conjunction, Operator, RuleCondition, RuleSource
from app.rules.executor import execute_rule


def _table(rows: list[dict]) -> CanonicalTable:
    return CanonicalTable(
        tenant_id="t",
        source_id="s",
        table_name="transactions",
        columns=[
            ColumnSchema(name="amount", type=ColumnType.FLOAT),
            ColumnSchema(name="status", type=ColumnType.STRING),
            ColumnSchema(name="notes", type=ColumnType.STRING),
        ],
        rows=rows,
    )


def _rule(conditions: list[RuleCondition], conjunction=Conjunction.AND) -> CompiledRule:
    return CompiledRule(
        conditions=conditions,
        conjunction=conjunction,
        source=RuleSource.USER_AUTHORED,
        human_readable_description="test rule",
    )


def test_less_than_flags_correct_rows():
    table = _table([{"amount": 100}, {"amount": -5}, {"amount": 50}])
    rule = _rule([RuleCondition(field="amount", operator=Operator.LESS_THAN, value=0)])
    result = execute_rule(table, rule)
    assert result.flagged_row_indices == [1]
    assert result.check_name == "custom_rule"


def test_greater_than_flags_correct_rows():
    table = _table([{"amount": 100}, {"amount": 5000}])
    rule = _rule([RuleCondition(field="amount", operator=Operator.GREATER_THAN, value=1000)])
    result = execute_rule(table, rule)
    assert result.flagged_row_indices == [1]


def test_equals_and_not_equals():
    table = _table([{"status": "pending"}, {"status": "done"}])
    eq_rule = _rule([RuleCondition(field="status", operator=Operator.EQUALS, value="pending")])
    assert execute_rule(table, eq_rule).flagged_row_indices == [0]

    neq_rule = _rule([RuleCondition(field="status", operator=Operator.NOT_EQUALS, value="pending")])
    assert execute_rule(table, neq_rule).flagged_row_indices == [1]


def test_contains_is_case_insensitive():
    table = _table([{"notes": "URGENT review needed"}, {"notes": "all good"}])
    rule = _rule([RuleCondition(field="notes", operator=Operator.CONTAINS, value="urgent")])
    assert execute_rule(table, rule).flagged_row_indices == [0]


def test_matches_pattern():
    table = _table([{"notes": "ref-12345"}, {"notes": "no ref here"}])
    rule = _rule([RuleCondition(field="notes", operator=Operator.MATCHES_PATTERN, value=r"ref-\d+")])
    assert execute_rule(table, rule).flagged_row_indices == [0]


def test_in_set():
    table = _table([{"status": "failed"}, {"status": "done"}, {"status": "cancelled"}])
    rule = _rule([RuleCondition(field="status", operator=Operator.IN_SET, value=["failed", "cancelled"])])
    assert execute_rule(table, rule).flagged_row_indices == [0, 2]


def test_is_null_and_is_not_null():
    table = _table([{"notes": ""}, {"notes": "something"}, {"notes": None}])
    null_rule = _rule([RuleCondition(field="notes", operator=Operator.IS_NULL, value=None)])
    assert execute_rule(table, null_rule).flagged_row_indices == [0, 2]

    not_null_rule = _rule([RuleCondition(field="notes", operator=Operator.IS_NOT_NULL, value=None)])
    assert execute_rule(table, not_null_rule).flagged_row_indices == [1]


def test_and_conjunction_requires_all_conditions():
    table = _table([
        {"amount": -50, "status": "pending"},
        {"amount": -50, "status": "done"},
        {"amount": 100, "status": "pending"},
    ])
    rule = _rule(
        [
            RuleCondition(field="amount", operator=Operator.LESS_THAN, value=0),
            RuleCondition(field="status", operator=Operator.EQUALS, value="pending"),
        ],
        conjunction=Conjunction.AND,
    )
    assert execute_rule(table, rule).flagged_row_indices == [0]


def test_or_conjunction_requires_any_condition():
    table = _table([
        {"amount": -50, "status": "done"},
        {"amount": 100, "status": "pending"},
        {"amount": 100, "status": "done"},
    ])
    rule = _rule(
        [
            RuleCondition(field="amount", operator=Operator.LESS_THAN, value=0),
            RuleCondition(field="status", operator=Operator.EQUALS, value="pending"),
        ],
        conjunction=Conjunction.OR,
    )
    assert execute_rule(table, rule).flagged_row_indices == [0, 1]


def test_missing_value_does_not_match_non_null_operators():
    """A blank field can't satisfy greater_than/equals/etc — should be
    a non-match, not a crash."""
    table = _table([{"amount": None}, {"amount": 100}])
    rule = _rule([RuleCondition(field="amount", operator=Operator.GREATER_THAN, value=50)])
    result = execute_rule(table, rule)
    assert result.flagged_row_indices == [1]  # row 0 safely skipped, no crash


def test_malformed_comparison_does_not_crash():
    """A non-numeric value against a numeric operator should fail that
    row's condition, not raise."""
    table = _table([{"amount": "not-a-number"}, {"amount": 100}])
    rule = _rule([RuleCondition(field="amount", operator=Operator.GREATER_THAN, value=50)])
    result = execute_rule(table, rule)
    assert result.flagged_row_indices == [1]


def test_detail_carries_human_readable_description():
    table = _table([{"amount": -5}])
    rule = CompiledRule(
        conditions=[RuleCondition(field="amount", operator=Operator.LESS_THAN, value=0)],
        conjunction=Conjunction.AND,
        source=RuleSource.USER_AUTHORED,
        human_readable_description="Flag negative transaction amounts",
    )
    result = execute_rule(table, rule)
    assert result.detail == "Flag negative transaction amounts"
