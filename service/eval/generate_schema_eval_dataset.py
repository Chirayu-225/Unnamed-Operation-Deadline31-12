"""
Builds a small, deliberately-connected 3-table schema for validating
/scans/schema structurally — multi-file upload, per-table scoring, and
cross-table referential-integrity findings — against known ground
truth, rather than eyeballing the response.

This is a NARROWER eval than generate_datasets.py's three domains: it
isn't trying to measure detection quality across all 6 planted-issue
categories again (that's already covered, per-table, by the existing
crm_leads/ecommerce/hr_employees datasets and run_eval.py). Its only
job is to prove the schema-scan endpoint's STRUCTURAL claims hold on
something more realistic than a 3-row unit-test fixture: multiple
tables, multiple foreign-key relationships (including two different
tables both referencing the same target table), and a per-table
aggregate score that's actually weighted by row count.

Schema (3 tables, 2 distinct target relationships):
  accounts.csv       (id, name, industry)              — 30 rows, no FKs
  contacts.csv       (id, account_id, email)            — 40 rows
  opportunities.csv  (id, account_id, amount, stage)     — 20 rows

Both contacts and opportunities reference accounts — on purpose, to
prove cross_table_findings reports each relationship separately rather
than collapsing them because they share a to_table. Every planted
orphaned foreign key uses an out-of-range id (9000+) so it can never
coincidentally collide with a real row — same convention as
generate_datasets.py's referential_integrity_bad_ref category.

Run from service/:
    PYTHONPATH=. python3 eval/generate_schema_eval_dataset.py
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

SEED = 20260925
OUT_DIR = Path(__file__).parent / "datasets" / "schema"

N_ACCOUNTS = 30
N_CONTACTS = 40
N_OPPORTUNITIES = 20

# How many rows in each child table get a deliberately orphaned FK.
N_ORPHANED_CONTACTS = 5
N_ORPHANED_OPPORTUNITIES = 4

INDUSTRIES = ["Technology", "Retail", "Healthcare", "Manufacturing", "Finance"]
STAGES = ["Prospecting", "Qualification", "Proposal", "Closed Won", "Closed Lost"]


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def generate() -> dict:
    rng = random.Random(SEED)

    # --- accounts.csv (no FKs — the root of the schema) ---
    account_ids = list(range(1, N_ACCOUNTS + 1))
    account_rows = [
        [aid, f"Account {aid}", rng.choice(INDUSTRIES)] for aid in account_ids
    ]
    _write_csv(OUT_DIR / "accounts.csv", ["id", "name", "industry"], account_rows)

    # --- contacts.csv (account_id -> accounts.id) ---
    orphan_contact_rows = set(rng.sample(range(N_CONTACTS), N_ORPHANED_CONTACTS))
    contact_rows = []
    for i in range(N_CONTACTS):
        cid = i + 1
        if i in orphan_contact_rows:
            account_id = 9000 + i  # deliberately out of range
        else:
            account_id = rng.choice(account_ids)
        contact_rows.append([cid, account_id, f"contact{cid}@example.com"])
    _write_csv(OUT_DIR / "contacts.csv", ["id", "account_id", "email"], contact_rows)

    # --- opportunities.csv (account_id -> accounts.id, a SECOND
    #     relationship into the same target table as contacts) ---
    orphan_opp_rows = set(rng.sample(range(N_OPPORTUNITIES), N_ORPHANED_OPPORTUNITIES))
    opportunity_rows = []
    for i in range(N_OPPORTUNITIES):
        oid = i + 1
        if i in orphan_opp_rows:
            account_id = 9500 + i  # different out-of-range block than contacts'
        else:
            account_id = rng.choice(account_ids)
        amount = rng.randint(1000, 250000)
        opportunity_rows.append([oid, account_id, amount, rng.choice(STAGES)])
    _write_csv(
        OUT_DIR / "opportunities.csv",
        ["id", "account_id", "amount", "stage"],
        opportunity_rows,
    )

    ground_truth = {
        "tables": {
            "accounts": {"row_count": N_ACCOUNTS},
            "contacts": {"row_count": N_CONTACTS},
            "opportunities": {"row_count": N_OPPORTUNITIES},
        },
        "cross_table_findings": [
            {
                "from_table": "contacts",
                "from_column": "account_id",
                "to_table": "accounts",
                "flagged_row_count": N_ORPHANED_CONTACTS,
            },
            {
                "from_table": "opportunities",
                "from_column": "account_id",
                "to_table": "accounts",
                "flagged_row_count": N_ORPHANED_OPPORTUNITIES,
            },
        ],
    }
    (OUT_DIR / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))
    return ground_truth


if __name__ == "__main__":
    gt = generate()
    print(f"Wrote schema eval dataset to {OUT_DIR}/")
    print(json.dumps(gt, indent=2))
