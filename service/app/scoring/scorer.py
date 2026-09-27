"""
Scorecard — rolls up check and agent output into per-metric scores and
one overall score. Pure aggregation: this module runs NO detection
itself, only interprets what a ScanResult already produced — which is
what keeps it reusable regardless of which connector or which checks
ran.

Internally, this module converts CheckResult/SemanticFlag/VerifiedFlag
into the unified `Finding` representation (app.domain.finding) FIRST,
then computes every score off that single list — rather than the two
separate code paths (one for deterministic checks, one for semantic
flags) this module used before. That's the actual point of the
Finding refactor: the scorer no longer needs to understand multiple
species of "something went wrong."

This is deliberately behavior-preserving, not a scoring redesign: the
numeric weight for each Finding is computed from the exact same source
facts (which fields a deterministic check attributed a flag to, and a
semantic flag's verification label) that produced these same numbers
before the refactor — see `_finding_weight` below. Finding.severity
(a separate, human-facing categorical label) is NOT what scoring
weight is derived from; reversing severity back into a number would
have been lossy and unnecessary, since the real source facts are
still right there on the Finding. `tests/test_scorer.py`'s existing
assertions — written against the pre-refactor numbers — are what prove
this stayed true.

Confidence-weighted, not a raw flag count:
- A deterministic check's flag counts at full weight (1.0) by default,
  UNLESS the check attributed the flag to specific field(s) (via
  CheckResult.flagged_fields) — in which case field criticality takes
  over: a flag on a required (non-nullable) field weighs
  CRITICAL_FIELD_WEIGHT (2.0), an optional field weighs
  OPTIONAL_FIELD_WEIGHT (1.0), and a row flagged on more than one
  field takes the highest of the two. Checks that don't populate
  flagged_fields (DuplicateCheck — duplication is a whole-row
  property, not one field's fault) simply fall back to the flat 1.0
  weight, exactly as before this feature existed.
- A verified semantic flag counts at CONFIRMED=1.0 or
  NEEDS_REVIEW=0.5 weight. REJECTED flags contribute 0 — they never
  become a Finding at all (see findings_from_semantic_flags), which is
  the Finding-converter doing up front what this module used to do
  independently as a safety net.
- An UNVERIFIED semantic flag (no verifier was run this scan) is
  treated as NEEDS_REVIEW-equivalent (0.5) by default — an
  unconfirmed claim from the generator alone should never weigh as
  heavily as a checked fact or a genuinely verified one.

A row flagged more than once under the SAME metric (e.g. two checks
both touching validity) is weighted by its single strongest signal via
max(), not summed — a row is either "flagged under this metric" or
not; stacking multiple flags on the same row and metric shouldn't
double-penalize it. A row flagged under DIFFERENT metrics correctly
counts against each independently, since those are separate
dimensions of quality.

Field criticality is derived from ColumnSchema.nullable — a field
already marked required in the canonical model is treated as more
important, reusing information that already exists rather than
inventing a new criticality concept. An explicit, finer-grained
criticality score (beyond required/optional) is a reasonable future
extension, not something this module tries to guess at now.

The prompt-injection backstop (app.checks.injection_detection,
check_name "prompt_injection_check") is likewise NOT included in this
module's scoring, by the same check_name-string-matching convention
`main.py` already uses for `referential_integrity_check`'s cross-table
handling. A row containing a hostile payload is a security event, not
a data-quality defect — averaging it into the accuracy score would
imply an active compromise is just a typo (see the row's own
handling in app.agent.generator.GeneratorAgent.run, which routes it
to `ScanResult.quarantined_row_indices` instead of the ordinary
`flagged_row_indices`). Concretely: its CheckResult is skipped when
building `findings` below (so it produces no Finding at all, ever),
and ACCURACY counts as "evaluated" purely from whether the semantic
layer ran a batch (`semantic_iterations > 0`) — this check running
alone no longer makes ACCURACY look evaluated the way it used to,
since the thing that ran isn't a quality judgment.

Cross-table semantic findings are NOT included in this module's
scoring — that was true before this refactor too (SchemaScanResponse's
aggregate_score in main.py is a row-count-weighted average of each
table's own single-table scorecard) and stays true now; this refactor
gives cross-table findings the same Finding representation via
findings_from_cross_table_semantic for future evidence/UI use, without
changing what gets scored.

--- Coverage tracking and the overall-score cap (added after a code
review reproduced two concrete failure modes with real probe data) ---

Bug 1 — "not evaluated" silently scored as "perfect": previously,
every metric defaulted to a flagged_weight of 0 (and therefore a score
of 100.0) whenever no Finding touched it, with no distinction between
"every applicable check ran and found nothing" and "no check for this
metric ever ran at all" (e.g. CONSISTENCY on a table with zero numeric
columns — OutlierCheck's applies_to() is False, so nothing evaluates
that dimension, yet it still reported a perfect 100). A metric is now
`evaluated` only if at least one deterministic CheckResult under that
category actually ran (regardless of what it found), or — for
ACCURACY specifically — the semantic layer ran at least one batch
(`scan_result.semantic_iterations > 0`; PromptInjectionCheck alone
also counts, same as any other deterministic check). An unevaluated
metric reports `score=None` and is excluded from the weighted overall
average entirely, rather than silently padding it with a 100 the data
never earned.

Bug 2 — a single severe metric gets diluted away by four healthy ones:
reproduced directly — a table with 40% of a REQUIRED field blank
scored completeness=20.0 in isolation (correctly alarming) but an
*overall_score* of 84.0, because a straight 5-way average let four
untouched, trivially-100 metrics absorb the one real problem. Real
customers read the single headline number; a severity floor is what
keeps that number honest. `_OVERALL_CRITICAL_CAP_ALLOWANCE` caps
overall_score at (worst evaluated metric's score + that allowance) —
so one badly-scoring dimension can pull the headline number down
toward itself, rather than being smoothed away by unrelated metrics
that happen to be clean. This only ever LOWERS overall_score relative
to the plain weighted average; a table with no single bad metric is
completely unaffected (see test_full_pipeline_frozen_baseline_catches_scoring_drift,
whose pinned 76.0 is unchanged by this cap).

Bug 3 (added alongside the Quarantine Model's severity-tiering fix,
reproduced by a code review rather than a probe table this time) — a
quarantined row was counting as "evaluated and clean" in ACCURACY's own
denominator: the per-metric formula divides flagged_weight by
total_rows, and total_rows was unconditionally the WHOLE table's row
count, even though quarantined rows are structurally never sampled by
the semantic layer and therefore can never contribute flagged_weight
either. A table with several rows quarantined would report a
misleadingly high ACCURACY score — the numerator correctly excluded
those rows' (nonexistent) semantic findings, but the denominator still
credited them as if they'd been checked and found fine. Fixed by
giving ACCURACY specifically a reduced denominator
(`accuracy_total_rows = total_rows - quarantined_row_count`) — see
`compute_scorecard`'s own comment. Every other metric keeps the
unmodified `total_rows`, since their deterministic checks really did
run over every row, quarantined or not.

Deliberately NOT touched by this pass: the per-metric formula itself
(100 * (1 - flagged_weight / total_rows)) and the field-criticality
weight constants. An initial instinct was to rescale the denominator
so a weight above 1.0 (the 2.0 "required field" tier) could never
mechanically approach total_rows — but every existing field-criticality
test (test_flag_on_required_field_weighs_double_an_optional_one and
neighbors) pins exact numbers under the CURRENT formula, and that
feature is real, intentional, already-tested behavior, not the bug
under investigation. Rescaling it would have silently changed
already-correct behavior as a side effect of fixing a different,
narrower problem. The two fixes above are the ones that were actually
reproduced as wrong; nothing else in this module's arithmetic changed.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agent.generator import ScanResult
from app.canonical.models import CanonicalTable, ColumnSchema
from app.checks.base import MetricCategory
from app.domain.finding import (
    CheckType,
    Finding,
    VerificationStatus,
    findings_from_check_result,
    findings_from_semantic_flags,
)

_ALL_METRICS = list(MetricCategory)

_CONFIRMED_WEIGHT = 1.0
_NEEDS_REVIEW_WEIGHT = 0.5
_UNVERIFIED_SEMANTIC_WEIGHT = 0.5

# Field-criticality weights — a flag on a required field counts for
# more than one on an optional field, instead of every flagged row
# being treated identically regardless of which column caused it.
_CRITICAL_FIELD_WEIGHT = 2.0
_OPTIONAL_FIELD_WEIGHT = 1.0

# Semantic/verified flags don't carry their own MetricCategory (unlike
# deterministic checks) — they represent general plausibility
# judgment, which maps most naturally onto "accuracy": does the data
# reflect reality correctly, not just internal completeness/format.
_SEMANTIC_METRIC = MetricCategory.ACCURACY

# check_name of the deterministic prompt-injection backstop — excluded
# from Finding conversion and from evaluated-metric tracking below.
# Same string-matching convention main.py already uses for
# "referential_integrity_check".
_INJECTION_CHECK_NAME = "prompt_injection_check"

# How far overall_score is allowed to drift above the single worst
# evaluated metric — see the module docstring's "Bug 2" note. Picked
# to be generous enough that a genuinely well-rounded scan (every
# metric in the 80s-90s) is never touched, while still preventing one
# severe metric from being averaged away by clean ones (see the
# reproduced 84.0-from-a-20.0-completeness-problem case).
_OVERALL_CRITICAL_CAP_ALLOWANCE = 20.0


class MetricScore(BaseModel):
    metric: MetricCategory
    # None when `evaluated` is False — no applicable check (or, for
    # ACCURACY, no semantic pass) ever ran, so there is nothing honest
    # to report here. A caller must not treat a missing score as 100;
    # `evaluated` is the field to check first.
    score: float | None  # 0-100, or None when not evaluated
    flagged_weight: float  # confidence-weighted sum contributing to this metric
    total_rows: int
    # Whether at least one applicable check (deterministic, or the
    # semantic layer for ACCURACY) actually ran for this metric this
    # scan. False means `score` is None — see the module docstring.
    evaluated: bool = True


class ScoreCard(BaseModel):
    table_name: str
    metric_scores: list[MetricScore]
    overall_score: float  # 0-100, weighted average of EVALUATED metric_scores,
    # capped per _OVERALL_CRITICAL_CAP_ALLOWANCE — see module docstring.
    # 100.0 in the degenerate case where nothing was evaluated at all.


def _field_criticality_weight(column: ColumnSchema | None) -> float:
    if column is None:
        return _OPTIONAL_FIELD_WEIGHT  # unknown field -> safe, conservative default
    return _CRITICAL_FIELD_WEIGHT if not column.nullable else _OPTIONAL_FIELD_WEIGHT


def _finding_weight(finding: Finding, columns_by_name: dict[str, ColumnSchema]) -> float:
    """The scorer's own numeric weight for one Finding — computed from
    the same source facts (affected_fields for deterministic;
    verification_status for semantic) that produced these exact
    numbers before the Finding refactor, not from `finding.severity`
    (a separate, display-oriented label)."""
    if finding.check_type == CheckType.DETERMINISTIC:
        if not finding.affected_fields:
            return _CONFIRMED_WEIGHT
        return max(_field_criticality_weight(columns_by_name.get(f)) for f in finding.affected_fields)

    # Semantic (single-table). Cross-table findings don't reach this
    # function at all — see module docstring.
    if finding.verification_status == VerificationStatus.CONFIRMED:
        return _CONFIRMED_WEIGHT
    if finding.verification_status == VerificationStatus.NEEDS_REVIEW:
        return _NEEDS_REVIEW_WEIGHT
    if finding.verification_status is None:
        return _UNVERIFIED_SEMANTIC_WEIGHT
    return 0.0  # REJECTED never reaches here (excluded by the converter), kept as a safe fallback


def compute_scorecard(
    scan_result: ScanResult,
    table: CanonicalTable,
    metric_weights: dict[MetricCategory, float] | None = None,
) -> ScoreCard:
    total_rows = len(table.rows)
    # ACCURACY's real denominator excludes quarantined rows (see
    # app/agent/generator.py's ScanResult.quarantined_row_indices) —
    # those rows are structurally never sampled by the semantic layer,
    # so counting them in the "how many rows were evaluated" denominator
    # would silently treat "never reasoned over" the same as
    # "reasoned over and found clean," inflating the score exactly the
    # way Bug 1 in this module's docstring already warned against for
    # the metric-level case. Every OTHER metric still uses the full
    # total_rows: their deterministic checks ran over every row,
    # quarantined or not, so nothing needs adjusting there.
    quarantined_count = len(getattr(scan_result, "quarantined_row_indices", None) or [])
    accuracy_total_rows = max(0, total_rows - quarantined_count)
    columns_by_name = {c.name: c for c in table.columns}
    nullable_by_field = {c.name: c.nullable for c in table.columns}

    weights = {m: 1.0 for m in _ALL_METRICS}
    if metric_weights:
        weights.update(metric_weights)

    # Build the unified Finding[] first — this is the actual point of
    # the refactor: everything below scores off ONE list, regardless
    # of which layer produced each finding.
    verified_by_row = {v.row_index: v for v in scan_result.verified_flags}
    findings: list[Finding] = []
    for check_result in scan_result.check_results:
        if check_result.check_name == _INJECTION_CHECK_NAME:
            continue  # security event, not a quality Finding — see module docstring
        findings.extend(
            findings_from_check_result(check_result, scan_result.table_name, nullable_by_field)
        )
    findings.extend(
        findings_from_semantic_flags(scan_result.semantic_flags, verified_by_row, scan_result.table_name)
    )

    row_weight_by_metric: dict[MetricCategory, dict[int, float]] = {m: {} for m in _ALL_METRICS}
    for finding in findings:
        bucket = row_weight_by_metric[finding.category]
        row_idx = finding.affected_rows[0]
        w = _finding_weight(finding, columns_by_name)
        bucket[row_idx] = max(bucket.get(row_idx, 0.0), w)

    # A metric is "evaluated" only if something actually ran for it —
    # never inferred from whether it produced any findings, since
    # "ran and found nothing" and "never ran" must not look identical.
    # Deterministic: at least one CheckResult under this category.
    # ACCURACY additionally counts as evaluated when the semantic layer
    # ran at least one batch this scan, even if PromptInjectionCheck
    # (the only deterministic ACCURACY check) didn't apply.
    evaluated_metrics: set[MetricCategory] = {
        r.metric for r in scan_result.check_results if r.check_name != _INJECTION_CHECK_NAME
    }
    if getattr(scan_result, "semantic_iterations", 0) > 0:
        evaluated_metrics.add(_SEMANTIC_METRIC)

    metric_scores: list[MetricScore] = []
    weighted_sum = 0.0
    weight_total = 0.0
    evaluated_scores: list[float] = []

    for metric in _ALL_METRICS:
        is_evaluated = metric in evaluated_metrics
        flagged_weight = sum(row_weight_by_metric[metric].values())
        # See accuracy_total_rows' own comment above — ACCURACY is the
        # one metric whose real denominator isn't the whole table.
        denom = accuracy_total_rows if metric == _SEMANTIC_METRIC else total_rows

        if not is_evaluated:
            metric_scores.append(
                MetricScore(
                    metric=metric,
                    score=None,
                    flagged_weight=flagged_weight,
                    total_rows=denom,
                    evaluated=False,
                )
            )
            continue

        score = 100.0 if denom == 0 else max(0.0, 100.0 * (1 - flagged_weight / denom))
        score = round(score, 1)

        metric_scores.append(
            MetricScore(
                metric=metric,
                score=score,
                flagged_weight=flagged_weight,
                total_rows=denom,
                evaluated=True,
            )
        )

        w = weights.get(metric, 1.0)
        weighted_sum += score * w
        weight_total += w
        evaluated_scores.append(score)

    if weight_total > 0:
        overall = weighted_sum / weight_total
        # Severity cap — see module docstring's "Bug 2". Only ever
        # pulls overall DOWN toward the worst evaluated metric; never
        # raises it.
        overall = min(overall, min(evaluated_scores) + _OVERALL_CRITICAL_CAP_ALLOWANCE)
        overall = round(max(0.0, overall), 1)
    else:
        # Nothing was evaluated at all (e.g. an empty table) — no
        # honest number to compute, so this is the one place a default
        # of 100.0 is legitimate rather than a masked gap.
        overall = 100.0

    return ScoreCard(
        table_name=scan_result.table_name,
        metric_scores=metric_scores,
        overall_score=overall,
    )
