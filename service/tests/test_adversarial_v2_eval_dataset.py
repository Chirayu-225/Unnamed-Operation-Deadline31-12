"""
No-LLM-needed checks on the second-generation (evasion-vector)
adversarial dataset — see eval/generate_adversarial_v2_dataset.py.
Mirrors test_adversarial_eval_dataset.py's structure for v1; kept as a
separate file since this is a separate, additional suite.
"""

import json
from pathlib import Path

from app.agent.generator import GeneratorAgent
from app.canonical.models import CanonicalTable
from app.connectors.base import ConnectorConfig
from app.connectors.csv_connector import CSVConnector

DATASET_DIR = Path(__file__).parent.parent / "eval" / "datasets" / "adversarial_v2"


def _load_table(csv_name: str) -> CanonicalTable:
    config = ConnectorConfig(
        tenant_id="test", source_id="test", settings={"file_path": str(DATASET_DIR / csv_name)}
    )
    return CSVConnector(config).extract()[0]


def _ground_truth() -> dict:
    return json.loads((DATASET_DIR / "ground_truth_v2.json").read_text())["rows"]


def test_control_and_attack_variants_have_the_same_row_count():
    control = _load_table("leads_control_v2.csv")
    attack = _load_table("leads_attack_v2.csv")
    assert len(control.rows) == len(attack.rows)


def test_control_and_attack_variants_only_differ_in_notes():
    control = _load_table("leads_control_v2.csv")
    attack = _load_table("leads_attack_v2.csv")
    for i, (c, a) in enumerate(zip(control.rows, attack.rows)):
        for key in ("company", "email", "industry", "amount"):
            assert c.get(key) == a.get(key), f"row {i} field '{key}' differs — isolation broken"


def test_every_row_flagged_as_carrying_an_injection_actually_has_different_notes():
    control = _load_table("leads_control_v2.csv")
    attack = _load_table("leads_attack_v2.csv")
    gt = _ground_truth()
    for i_str, meta in gt.items():
        if meta.get("injection_technique"):
            i = int(i_str)
            assert control.rows[i]["notes"] != attack.rows[i]["notes"], (
                f"row {i} is labeled with injection_technique={meta['injection_technique']!r} "
                "but its notes are identical between variants"
            )


def test_ground_truth_covers_every_row_exactly_once():
    control = _load_table("leads_control_v2.csv")
    gt = _ground_truth()
    assert set(gt.keys()) == {str(i) for i in range(len(control.rows))}


def test_all_four_evasion_vectors_are_represented():
    """The whole point of v2 over v1 — confirm the dataset actually
    covers all four evasion vectors discussed (paraphrase, lexical
    obfuscation, logical reframing, contextual camouflage), not just
    some subset, so a passing eval run actually means what it claims."""
    gt = _ground_truth()
    techniques = {meta["injection_technique"] for meta in gt.values() if meta.get("injection_technique")}
    assert techniques == {
        "semantic_paraphrase",
        "lexical_obfuscation",
        "logical_reframing",
        "contextual_camouflage",
    }


def test_deterministic_anchor_flags_regardless_of_notes_content():
    """Same anchor-row principle as v1: a blank required field is a
    pure-code check with no LLM in its path, so it must be flagged in
    both variants unconditionally, with no `llm` argument needed to
    prove it."""
    control = _load_table("leads_control_v2.csv")
    attack = _load_table("leads_attack_v2.csv")
    gt = _ground_truth()

    anchor_idx = next(i for i, meta in gt.items() if meta.get("role") == "deterministic_anchor")
    anchor_idx = int(anchor_idx)

    control_result = GeneratorAgent().run(control)  # no llm -> deterministic checks only
    attack_result = GeneratorAgent().run(attack)

    assert anchor_idx in control_result.flagged_row_indices
    assert anchor_idx in attack_result.flagged_row_indices


def test_deterministic_only_run_never_flags_the_clean_baseline_rows():
    control = _load_table("leads_control_v2.csv")
    attack = _load_table("leads_attack_v2.csv")
    gt = _ground_truth()

    control_result = GeneratorAgent().run(control)
    attack_result = GeneratorAgent().run(attack)

    for i_str, meta in gt.items():
        if meta.get("must_not_flag") is True:
            i = int(i_str)
            assert i not in control_result.flagged_row_indices
            assert i not in attack_result.flagged_row_indices


def test_amount_column_has_no_extreme_values_that_would_skew_outlier_baseline():
    """Regression guard against the exact bug caught in an earlier
    draft of this dataset: if the numeric column's values are mostly
    similar with one or two wild outliers, IQR-based OutlierCheck can
    flag the WRONG rows (or the right rows for the wrong reason). This
    dataset deliberately keeps every amount in a similar order of
    magnitude so the outlier check stays uninvolved in what this eval
    measures."""
    control = _load_table("leads_control_v2.csv")
    amounts = [float(row["amount"]) for row in control.rows]
    assert min(amounts) > 0
    assert max(amounts) / min(amounts) < 3.0, "amount spread is wide enough to risk skewing IQR baseline"
