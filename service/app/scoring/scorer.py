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

Cross-table semantic findings are NOT included in this module's
scoring — that was true before this refactor too (SchemaScanResponse's
aggregate_score in main.py is a row-count-weighted average of each
table's own single-table scorecard) and stays true now; this refactor
gives cross-table findings the same Finding representation via
findings_from_cross_table_semantic for future evidence/UI use, without
changing what gets scored.
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


class MetricScore(BaseModel):
    metric: MetricCategory
    score: float  # 0-100
    flagged_weight: float  # confidence-weighted sum contributing to this metric
    total_rows: int


class ScoreCard(BaseModel):
    table_name: str
    metric_scores: list[MetricScore]
    overall_score: float  # 0-100, weighted average of metric_scores


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

    metric_scores: list[MetricScore] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for metric in _ALL_METRICS:
        flagged_weight = sum(row_weight_by_metric[metric].values())
        score = 100.0 if total_rows == 0 else max(0.0, 100.0 * (1 - flagged_weight / total_rows))

        metric_scores.append(
            MetricScore(
                metric=metric,
                score=round(score, 1),
                flagged_weight=flagged_weight,
                total_rows=total_rows,
            )
        )

        w = weights.get(metric, 1.0)
        weighted_sum += score * w
        weight_total += w

    overall = round(weighted_sum / weight_total, 1) if weight_total > 0 else 100.0

    return ScoreCard(
        table_name=scan_result.table_name,
        metric_scores=metric_scores,
        overall_score=overall,
    )
