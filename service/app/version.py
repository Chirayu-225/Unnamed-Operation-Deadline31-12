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

DETECTION_VERSION = "1.1.0"  # bumped for the Finding-model refactor
SEMANTIC_PROMPT_VERSION = "2.0.0"  # anti-manipulation hardening + membership check
CROSS_TABLE_PROMPT_VERSION = "2.0.0"  # same hardening, cross-table variant
SCORING_VERSION = "1.1.0"  # Finding-based internals; numeric output unchanged
