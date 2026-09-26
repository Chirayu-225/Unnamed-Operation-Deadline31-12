"""
No-LLM-needed checks on the adversarial eval dataset (see
eval/generate_adversarial_eval_dataset.py) — runs in ordinary CI
without GROQ_API_KEY/GEMINI_API_KEY, unlike eval/run_adversarial_eval.py's
live attack run which needs real keys to actually test the semantic
layer. What CAN be verified without an LLM: the dataset's own
structural integrity, and the deterministic-checks-are-immune-by-
construction claim eval/run_adversarial_eval.py's report relies on
without re-proving it.
"""

import json
from pathlib import Path

from app.agent.generator import GeneratorAgent
from app.canonical.models import CanonicalTable
from app.connectors.base import ConnectorConfig
from app.connectors.csv_connector import CSVConnector

DATASET_DIR = Path(__file__).parent.parent / "eval" / "datasets" / "adversarial"


def _load_table(csv_name: str) -> CanonicalTable:
    config = ConnectorConfig(
        tenant_id="test", source_id="test", settings={"file_path": str(DATASET_DIR / csv_name)}
    )
    return CSVConnector(config).extract()[0]


def _ground_truth() -> dict:
    return json.loads((DATASET_DIR / "ground_truth.json").read_text())["rows"]


def test_control_and_attack_variants_have_the_same_row_count():
    control = _load_table("leads_control.csv")
    attack = _load_table("leads_attack.csv")
    assert len(control.rows) == len(attack.rows)


def test_control_and_attack_variants_only_differ_in_notes():
    control = _load_table("leads_control.csv")
    attack = _load_table("leads_attack.csv")
    for i, (c, a) in enumerate(zip(control.rows, attack.rows)):
        for key in ("company", "email", "industry", "amount"):
            assert c.get(key) == a.get(key), f"row {i} field '{key}' differs — isolation broken"


def test_every_row_flagged_as_carrying_an_injection_actually_has_different_notes():
    control = _load_table("leads_control.csv")
    attack = _load_table("leads_attack.csv")
    gt = _ground_truth()
    for i_str, meta in gt.items():
        if meta.get("injection_technique"):
            i = int(i_str)
            assert control.rows[i]["notes"] != attack.rows[i]["notes"], (
                f"row {i} is labeled with injection_technique={meta['injection_technique']!r} "
                "but its notes are identical between variants"
            )


def test_ground_truth_covers_every_row_exactly_once():
    control = _load_table("leads_control.csv")
    gt = _ground_truth()
    assert set(gt.keys()) == {str(i) for i in range(len(control.rows))}


def test_deterministic_check_flags_blank_email_row_regardless_of_injection_text():
    """Row 6's real issue is a blank email — a pure-code check with no
    LLM in its path. This should hold structurally regardless of
    anything in the notes field, in BOTH variants, without needing any
    API key to prove it — the injection payload can only ever have a
    chance of working against the SEMANTIC layer, never this one."""
    control = _load_table("leads_control.csv")
    attack = _load_table("leads_attack.csv")

    control_result = GeneratorAgent().run(control)  # no llm -> deterministic checks only
    attack_result = GeneratorAgent().run(attack)

    assert 6 in control_result.flagged_row_indices
    assert 6 in attack_result.flagged_row_indices


def test_deterministic_only_run_never_flags_the_clean_baseline_rows():
    """Sanity check with no LLM involved at all — the rows ground truth
    calls genuinely clean shouldn't trip any deterministic check either,
    in either variant."""
    control = _load_table("leads_control.csv")
    attack = _load_table("leads_attack.csv")
    gt = _ground_truth()

    control_result = GeneratorAgent().run(control)
    attack_result = GeneratorAgent().run(attack)

    for i_str, meta in gt.items():
        if meta.get("must_not_flag") is True:
            i = int(i_str)
            assert i not in control_result.flagged_row_indices
            assert i not in attack_result.flagged_row_indices
