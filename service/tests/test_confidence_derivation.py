from app.domain.confidence import derive_confidence


def test_deterministic_is_always_full_confidence_regardless_of_other_args():
    assert derive_confidence("deterministic", None) == 1.0
    assert derive_confidence("deterministic", "confirmed") == 1.0
    assert derive_confidence("deterministic", "needs_review", verification_failed=True) == 1.0


def test_single_table_base_rate_with_no_verifier_configured():
    assert derive_confidence("semantic_single_table", None) == 0.60


def test_cross_table_starts_lower_than_single_table_for_the_same_verification_state():
    single = derive_confidence("semantic_single_table", None)
    cross = derive_confidence("semantic_cross_table", None)
    assert cross < single


def test_confirmed_boosts_above_the_base_rate():
    base = derive_confidence("semantic_single_table", None)
    confirmed = derive_confidence("semantic_single_table", "confirmed")
    assert confirmed > base


def test_genuine_needs_review_leaves_base_rate_unchanged():
    base = derive_confidence("semantic_single_table", None)
    genuine = derive_confidence("semantic_single_table", "needs_review", verification_failed=False)
    assert genuine == base


def test_technical_failure_needs_review_is_strictly_lower_than_genuine_needs_review():
    genuine = derive_confidence("semantic_single_table", "needs_review", verification_failed=False)
    failed = derive_confidence("semantic_single_table", "needs_review", verification_failed=True)
    assert failed < genuine


def test_technical_failure_is_also_lower_than_no_verifier_at_all():
    """A verifier that was configured and genuinely tried but failed
    gives you LESS information than never having attempted verification
    — it shouldn't score as well as the plain "no verifier configured"
    case, which at least doesn't imply a check ran and came up empty."""
    unverified = derive_confidence("semantic_single_table", None)
    failed = derive_confidence("semantic_single_table", "needs_review", verification_failed=True)
    assert failed < unverified


def test_result_is_always_within_the_defensive_bounds():
    for check_type in ("deterministic", "semantic_single_table", "semantic_cross_table"):
        for status in (None, "confirmed", "needs_review"):
            for failed in (True, False):
                value = derive_confidence(check_type, status, verification_failed=failed)
                assert 0.0 < value <= 1.0


def test_accepts_real_enum_members_not_just_plain_strings():
    from app.domain.finding import CheckType, VerificationStatus

    assert derive_confidence(CheckType.DETERMINISTIC, None) == 1.0
    assert derive_confidence(CheckType.SEMANTIC_SINGLE_TABLE, VerificationStatus.CONFIRMED) == derive_confidence(
        "semantic_single_table", "confirmed"
    )
