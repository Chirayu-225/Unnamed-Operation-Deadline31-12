"""
Detection-logic versioning — attached to every scan's response
metadata so a scorecard can be traced back to exactly which prompt
and scoring logic produced it. This answers "why did this dataset
score differently after the evaluation logic changed?" without
needing any persistence: the version strings travel with the
response itself, not a database row.

Deliberately simple for this phase: hand-bumped constants, not a
computed hash of the actual prompt text. A hash would be tamper-proof
but unreadable; a bumped string is human-legible and good enough given
there's one developer and no concurrent-editing risk yet. Bump the
relevant constant whenever its corresponding prompt or scoring logic
changes — that discipline is what keeps this meaningful, so it's
called out explicitly at each prompt's own definition site too.

SEMANTIC_PROMPT_VERSION and CROSS_TABLE_PROMPT_VERSION were both
bumped in this same version as the row-index membership check and the
anti-manipulation prompt hardening (see semantic_reasoning.py and
cross_table_reasoning.py's system prompts) — a real example of exactly
the kind of change this version tracking exists to make visible.
"""

DETECTION_VERSION = "1.5.0"  # 1.2.0: NullCheck now flags a blank in ANY
# column (previously only non-nullable ones) — see
# app/checks/completeness.py's docstring for the reproduced
# nullable-from-data circularity bug this fixes. 1.3.0: DuplicateCheck
# now matches on real-world identity (an `email`-hinted column, or a
# name+company composite) before falling back to the original
# exact-full-row match — see app/checks/uniqueness.py's docstring for
# the reproduced bug (different-ID duplicates were invisible before).
# 1.4.0: the Quarantine Model — a row prompt_injection_check flags was
# pulled OUT of the ordinary flagged_row_indices union entirely (see
# app/agent/generator.py's GeneratorAgent.run) and structurally
# excluded from ever being sampled into a semantic-reasoning batch,
# single-table or cross-table (see _run_semantic_with_iteration's
# quarantined_indices param and main.py's cross-table pair filtering).
# 1.5.0: two corrections to 1.4.0, both from a code review that
# reproduced a concrete gap in it. First, a quarantined row no longer
# disappears from flagged_row_indices/FlaggedRowOut — it stays fully
# visible in the ordinary review list (with a "SECURITY (...)"-prefixed
# reason), since a security problem is never a reason for a row to look
# clean to a human reviewer; it just never contributes to any quality
# SCORE (still true, unchanged) and is still structurally excluded from
# semantic sampling (still true, unchanged). Second,
# app/checks/injection_detection.py's patterns are now split into HIGH
# and LOW confidence tiers — only a HIGH match quarantines a row; a LOW
# match (ordinary business language like "pre-approved", "compliance
# team") is reported (a low-severity SecurityFinding) but does NOT pull
# the row out of semantic review, fixing a reproduced false-positive-
# amplification problem where routine CRM/finance phrasing could
# silently blind semantic coverage over a large share of a clean table.
SEMANTIC_PROMPT_VERSION = "2.0.0"  # anti-manipulation hardening + membership check
CROSS_TABLE_PROMPT_VERSION = "2.0.0"  # same hardening, cross-table variant
SCORING_VERSION = "1.4.0"  # 1.2.0: per-metric evaluated/N/A tracking +
# the overall-score severity cap (see app/scoring/scorer.py's module
# docstring, "Bug 1"/"Bug 2") — unlike 1.1.0, this DOES change numeric
# output: a metric with nothing applicable now reports score=None
# instead of 100, and overall_score can no longer be diluted arbitrarily
# far above the worst evaluated metric. 1.3.0: the prompt-injection
# backstop (prompt_injection_check) no longer contributes to ACCURACY
# at all — a quarantined row is a security event, not a quality
# Finding, so it's excluded from both Finding conversion and
# evaluated-metric tracking (see scorer.py's module docstring). This
# also changes numeric output: a table whose only ACCURACY signal was
# an injection flag now reports ACCURACY as evaluated=False instead of
# a score dragged down by a security match. 1.4.0: Bug 3 — ACCURACY's
# own denominator now excludes quarantined rows
# (total_rows - quarantined_row_count) instead of the whole table, so a
# quarantined row is no longer silently credited as "evaluated and
# clean" in the percentage math just because it contributes zero
# flagged_weight. This LOWERS ACCURACY's apparent score on any table
# with quarantined rows compared to the unfixed 1.3.0 formula, since
# the unfixed version was inflating it by padding the denominator with
# rows that were never actually evaluated — a real correction, not a
# regression, per the module docstring's own worked example (10 rows,
# 4 quarantined, 1 unverified confirmed flag: 95.0 under the bug vs.
# the correct 91.7).
CONFIDENCE_DERIVATION_VERSION = "1.0.0"  # app/domain/confidence.py's base
# rates + confirmed-boost/technical-failure-penalty constants. Bump
# this whenever any of those numbers change — it's the one piece of
# scan-response metadata that ISN'T also covered by DETECTION_VERSION,
# since derive_confidence() is called after Finding conversion, not
# part of it, and a change to its constants alone wouldn't otherwise
# be visible in the versions a scan response carries.
