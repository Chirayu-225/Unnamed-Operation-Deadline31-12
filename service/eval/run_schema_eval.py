"""
Validates /scans/schema's STRUCTURAL claims against
eval/datasets/schema/'s known ground truth: multi-file upload actually
produces one response per table, cross-table referential-integrity
findings match the planted orphaned foreign keys exactly (not just
"some findings exist"), and the aggregate score is genuinely the
row-count-weighted mean it claims to be, not a coincidence.

Deliberately does NOT need GROQ_API_KEY/GEMINI_API_KEY — this is the
step-2 structural validation the build order calls for before deciding
whether cross-table semantic judgment (which WOULD need an LLM) is
worth building at all. Uses FastAPI's TestClient directly rather than a
live uvicorn process, so it's fast, deterministic, and runnable in CI
with no server to stand up.

Run from service/:
    PYTHONPATH=. python3 eval/run_schema_eval.py
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

DATASET_DIR = Path(__file__).parent / "datasets" / "schema"


def _load_ground_truth() -> dict:
    return json.loads((DATASET_DIR / "ground_truth.json").read_text())


def _open_files() -> list[tuple[str, tuple[str, bytes, str]]]:
    files = []
    for csv_path in sorted(DATASET_DIR.glob("*.csv")):
        files.append(("files", (csv_path.name, csv_path.read_bytes(), "text/csv")))
    return files


def run() -> bool:
    gt = _load_ground_truth()
    client = TestClient(app)

    print(f"Posting {len(list(DATASET_DIR.glob('*.csv')))} tables to /scans/schema...")
    resp = client.post("/scans/schema", files=_open_files())

    if resp.status_code != 200:
        print(f"FAIL — endpoint returned {resp.status_code}: {resp.text}")
        return False

    body = resp.json()
    ok = True

    # --- per-table presence + row counts ---
    print("\n--- Per-table structural check ---")
    tables_by_name = {t["table_name"]: t for t in body["tables"]}
    for name, expected in gt["tables"].items():
        actual = tables_by_name.get(name)
        if actual is None:
            print(f"FAIL — expected table '{name}' missing from response")
            ok = False
            continue
        row_match = actual["total_rows"] == expected["row_count"]
        status = "OK" if row_match else "FAIL"
        print(f"{status} — {name}: {actual['total_rows']} rows (expected {expected['row_count']})")
        ok = ok and row_match

    # --- cross-table findings: exact match, order-independent ---
    print("\n--- Cross-table findings check ---")

    def _key(f: dict) -> tuple:
        return (f["from_table"], f["from_column"], f["to_table"])

    actual_by_key = {_key(f): f for f in body["cross_table_findings"]}
    expected_by_key = {_key(f): f for f in gt["cross_table_findings"]}

    for key, expected in expected_by_key.items():
        actual = actual_by_key.get(key)
        if actual is None:
            print(f"FAIL — expected cross-table finding {key} missing")
            ok = False
            continue
        count_match = actual["flagged_row_count"] == expected["flagged_row_count"]
        status = "OK" if count_match else "FAIL"
        print(
            f"{status} — {key[0]}.{key[1]} -> {key[2]}: "
            f"{actual['flagged_row_count']} orphaned rows (expected {expected['flagged_row_count']})"
        )
        ok = ok and count_match

    unexpected = set(actual_by_key) - set(expected_by_key)
    if unexpected:
        print(f"FAIL — unexpected cross-table findings not in ground truth: {unexpected}")
        ok = False

    # --- aggregate score: recompute the weighted mean independently
    #     and check the endpoint's number matches, rather than trusting
    #     it did the arithmetic it claims to. ---
    print("\n--- Aggregate score check ---")
    total_rows = sum(t["total_rows"] for t in body["tables"])
    expected_aggregate = round(
        sum(t["overall_score"] * t["total_rows"] for t in body["tables"]) / total_rows, 2
    )
    aggregate_match = abs(body["aggregate_score"] - expected_aggregate) < 0.01
    status = "OK" if aggregate_match else "FAIL"
    print(f"{status} — aggregate_score={body['aggregate_score']} (recomputed {expected_aggregate})")
    ok = ok and aggregate_match

    print(f"\n{'PASS' if ok else 'FAIL'} — schema eval {'succeeded' if ok else 'found mismatches'}")
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if run() else 1)
