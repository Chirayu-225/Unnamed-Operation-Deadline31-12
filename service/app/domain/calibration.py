"""
Confidence calibration — the raw, self-reported LLM confidence is NOT
treated as a trustworthy probability here. Concrete evidence for why:
in a real run against this project's own eval data, four structurally
different flagged rows (one obvious industry mismatch, three subtler
ones) ALL came back from the generator with confidence=0.95 — a model
reporting the identical number regardless of case difficulty isn't
calibrated, it's a canned value. Treating that as "95% likely to be a
real issue" would be a false precision claim dressed up as a number.

Rather than fit calibration against a large labeled dataset (this
project doesn't have one, and manufacturing one would just be guessing
in a different shape), `calibrate()` derives a confidence figure from
OBSERVABLE, STRUCTURAL facts about how a flag was produced — hence
"calibration via subtlety, not via the model's own confidence report":

- `check_type` sets a base rate. A deterministic check is exact by
  construction (base 1.0, never adjusted — there's no "confidence" in
  a regex match or a null check). A single-table semantic judgment is
  one-hop pattern matching over one row (base 0.60). A cross-table
  semantic judgment requires resolving a foreign key AND reasoning
  about whether two different tables' rows are mutually consistent —
  a structurally harder, more failure-prone task with more places to
  go wrong — so it starts lower (base 0.50).
- Independent verification is the strongest available signal, since
  it's a genuinely different model (Gemini) checking the SAME claim
  the generator (Groq) made, not the same model grading its own work.
  A genuine CONFIRMED raises confidence substantially. A genuine
  NEEDS_REVIEW — the verifier actually ran and was honestly uncertain
  — leaves the base rate unchanged, because "uncertain" is real
  information about the case, not an absence of information.
- A NEEDS_REVIEW caused by a TECHNICAL failure (the verifier API call
  itself failed or returned nothing usable — see `verification_failed`
  below) is NOT the same as a genuine "I looked and I'm not sure." It
  means no second opinion was obtained at all, which is LESS evidence
  than an ordinary unverified semantic flag, not equal to it. This
  distinction was invisible before this module: both cases collapsed
  into the identical NEEDS_REVIEW label, with the difference visible
  only in a human-readable note nothing upstream actually read. This
  gap is not hypothetical — it was observed directly in this project's
  own testing: a Gemini free-tier quota exhaustion mid-scan produced
  verifier_notes reading "verification unavailable — 429
  RESOURCE_EXHAUSTED" for four different rows, each one labeled
  identically to a considered, honestly-uncertain verdict.

Deliberately NOT attempted here: cross-finding corroboration (e.g.
boosting a semantic flag that an independent deterministic check also
caught on the same row). That needs visibility across the WHOLE
finding set at once, which is a natural next step for this module but
a separate, larger change — left for a later pass rather than folded
in here, so this one stays small enough to verify in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only for type-checking — importing app.domain.finding at runtime
    # here would create a cycle (finding.py imports calibrate() below).
    # CheckType/VerificationStatus are (str, Enum) subclasses, so a
    # dict keyed on their plain string values (below) still matches a
    # real enum member passed in at runtime: str-Enum equality AND
    # hashing both fall through to the string value.
    from app.domain.finding import CheckType, VerificationStatus

_BASE_CONFIDENCE: dict[str, float] = {
    "deterministic": 1.0,
    "semantic_single_table": 0.60,
    "semantic_cross_table": 0.50,
}

_CONFIRMED_BOOST = 0.35
_TECHNICAL_FAILURE_PENALTY = 0.15

# Defensive bounds — never claim absolute certainty or absolute zero,
# even though no combination of today's constants actually reaches
# either edge. A future constant change shouldn't be able to silently
# produce a confidence outside a sane range.
_MIN_CONFIDENCE = 0.05
_MAX_CONFIDENCE = 0.99


def calibrate(
    check_type: "CheckType | str",
    verification_status: "VerificationStatus | str | None",
    verification_failed: bool = False,
) -> float:
    """Pure function — no LLM calls, no dependence on the raw
    self-reported confidence at all; that's the point (see module
    docstring). `verification_failed` distinguishes a NEEDS_REVIEW that
    came from a genuine verifier judgment (False) from one that came
    from the verifier call itself failing (True).

    Accepts either the real enum members or their plain string values
    — deliberately duck-typed, matching this codebase's existing
    convention for cross-module calls that would otherwise risk a
    circular import (see finding.py's converters)."""
    base = _BASE_CONFIDENCE.get(check_type, 0.5)  # type: ignore[arg-type]

    if check_type == "deterministic":
        return base  # exact by construction — never adjusted

    if verification_status == "confirmed":
        base += _CONFIRMED_BOOST
    elif verification_status == "needs_review" and verification_failed:
        base -= _TECHNICAL_FAILURE_PENALTY
    # A genuine "needs_review" (verifier ran, was honestly uncertain)
    # or None (no verifier configured at all) leaves the base rate
    # unchanged — see module docstring for why those aren't the same
    # as a technical failure, and aren't evidence in either direction.

    return max(_MIN_CONFIDENCE, min(_MAX_CONFIDENCE, base))
