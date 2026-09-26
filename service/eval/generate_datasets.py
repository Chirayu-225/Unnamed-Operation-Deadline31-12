"""
Forges realistic-but-synthetic multi-domain datasets with KNOWN planted
data-quality issues, for evaluating the agent's detection accuracy,
iteration-loop behavior, and custom-instruction reliability against
ground truth rather than eyeballing results.

Three domains, deliberately not all CRM, to give the "schema-agnostic"
claim something real to stand on:
  - crm_leads      (leads.csv + accounts.csv)   — Salesforce-shaped, the
                                                    product's actual target
  - ecommerce      (orders.csv + customers.csv) — a second multi-table
                                                    domain with a
                                                    different shape
  - hr_employees   (employees.csv, single table) — no FK-shaped table at
                                                     all, to prove the
                                                     referential-integrity
                                                     check's absence
                                                     doesn't break anything
                                                     and every other check
                                                     still works alone

Every table's own primary key column is deliberately named "id" (never
"<table>_id") — naming it e.g. "order_id" on the orders table would make
ReferentialIntegrityCheck's name-based heuristic treat it as a foreign key
into a table called "orders", find the orders table itself in the scan
context, and self-reference against a nonexistent "id" lookup — a bug in
the *dataset*, not the checker, but one that would silently corrupt every
number this eval produces. Column naming here is chosen carefully for
exactly that reason.

Each domain plants six categories of issue into an otherwise-clean table,
in DISJOINT row ranges (no row carries two planted issues) so precision/
recall math stays interpretable:
  - completeness_null              blank required field      (deterministic)
  - uniqueness_duplicate           exact full-row duplicate  (deterministic)
  - validity_format                malformed email/date      (deterministic)
  - consistency_outlier            statistically extreme     (deterministic)
  - referential_integrity_bad_ref  FK points at nothing       (deterministic)
  - semantic_mismatch              internally implausible     (LLM-ONLY —
                                    no deterministic check could ever
                                    catch this; e.g. "Joe's Bakery" filed
                                    under industry "Technology")

Duplicate pairs are two rows that are exact duplicates OF EACH OTHER
ONLY, never of a "clean" row elsewhere in the table — otherwise the
clean row's untainted index would also get flagged (DuplicateCheck
flags every member of a duplicate group), corrupting ground truth for
a row that was never meant to be an issue.

Run directly to (re)generate every dataset:
    PYTHONPATH=. python3 eval/generate_datasets.py
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

random.seed(42)  # reproducible across regenerations

OUT_DIR = Path(__file__).parent / "datasets"
OUT_DIR.mkdir(exist_ok=True)


def _write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> Path:
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_ground_truth(
    name: str,
    primary_table: str,
    related_tables: list[str],
    total_rows: int,
    categories: dict[str, list[int]],
    deterministic_categories: set[str],
) -> Path:
    all_issue_rows = sorted({i for rows in categories.values() for i in rows})
    deterministic_rows = sorted(
        {i for cat, rows in categories.items() if cat in deterministic_categories for i in rows}
    )
    semantic_only_rows = sorted(set(all_issue_rows) - set(deterministic_rows))
    clean_rows = sorted(set(range(total_rows)) - set(all_issue_rows))

    payload = {
        "dataset": name,
        "primary_table": primary_table,
        "related_tables": related_tables,
        "total_rows": total_rows,
        "categories": {cat: sorted(rows) for cat, rows in categories.items()},
        "deterministic_categories": sorted(deterministic_categories),
        "all_issue_rows": all_issue_rows,
        "deterministic_rows": deterministic_rows,
        "semantic_only_rows": semantic_only_rows,
        "clean_rows": clean_rows,
    }
    path = OUT_DIR / f"{name}_ground_truth.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


# ---------------------------------------------------------------------
# Domain 1: CRM leads (Salesforce-shaped — the product's actual target)
# ---------------------------------------------------------------------

_NON_TECH_BUSINESSES = [
    "Joe's Bakery", "Sunrise Diner", "Glow Nail Salon", "Corner Barbershop",
    "Fresh Leaf Florist", "Riverside Laundromat", "Maple Veterinary Clinic",
    "Old Town Bookstore", "Zen Yoga Studio", "Downtown Auto Repair",
]


def generate_crm_leads() -> None:
    n_accounts = 40
    accounts = [{"id": str(i), "name": f"Account {i}", "industry": "Technology"} for i in range(1, n_accounts + 1)]
    _write_csv("accounts", ["id", "name", "industry"], accounts)

    def clean_row(i: int) -> dict:
        account_id = (i % n_accounts) + 1
        return {
            "id": str(i),
            "email": f"contact{i}@corp{i}.com",
            "phone": f"+1-555-{1000 + i:04d}",
            "created_date": "2026-01-15",
            "amount": str(200 + (i * 37) % 3800),
            "account_id": str(account_id),
            "company": f"Corp{i} Software Solutions",
            "industry": "Technology",
        }

    rows: list[dict] = []
    categories: dict[str, list[int]] = {
        "completeness_null": [],
        "uniqueness_duplicate": [],
        "validity_format": [],
        "consistency_outlier": [],
        "referential_integrity_bad_ref": [],
        "semantic_mismatch": [],
    }

    # 0-89: clean
    for i in range(90):
        rows.append(clean_row(i))

    # 90-99: completeness — blank required field (email)
    for i in range(90, 100):
        r = clean_row(i)
        r["email"] = ""
        rows.append(r)
        categories["completeness_null"].append(i)

    # 100-105: uniqueness — 3 pairs, each pair duplicates ONLY itself
    for pair in range(3):
        base = clean_row(9000 + pair)
        idx_a, idx_b = 100 + pair * 2, 100 + pair * 2 + 1
        rows.append(dict(base))
        rows.append(dict(base))
        categories["uniqueness_duplicate"].extend([idx_a, idx_b])

    # 106-115: validity — malformed email or date, alternating
    for i in range(106, 116):
        r = clean_row(i)
        if i % 2 == 0:
            r["email"] = "not-an-email-at-all"
        else:
            r["created_date"] = "13/45/2026"  # invalid month/day
        rows.append(r)
        categories["validity_format"].append(i)

    # 116-120: consistency — extreme amount
    for i in range(116, 121):
        r = clean_row(i)
        r["amount"] = str(500_000 + i * 10_000)
        rows.append(r)
        categories["consistency_outlier"].append(i)

    # 121-127: referential integrity — nonexistent account
    for i in range(121, 128):
        r = clean_row(i)
        r["account_id"] = "9999"
        rows.append(r)
        categories["referential_integrity_bad_ref"].append(i)

    # 128-137: semantic mismatch — LLM-only, no deterministic check applies
    for offset, i in enumerate(range(128, 138)):
        r = clean_row(i)
        r["company"] = _NON_TECH_BUSINESSES[offset % len(_NON_TECH_BUSINESSES)]
        rows.append(r)
        categories["semantic_mismatch"].append(i)

    # 138-149: clean buffer
    for i in range(138, 150):
        rows.append(clean_row(i))

    assert len(rows) == 150, f"expected 150 rows, got {len(rows)}"
    _write_csv("leads", ["id", "email", "phone", "created_date", "amount", "account_id", "company", "industry"], rows)
    _write_ground_truth(
        "crm_leads", "leads", ["accounts"], len(rows), categories,
        deterministic_categories={
            "completeness_null", "uniqueness_duplicate", "validity_format",
            "consistency_outlier", "referential_integrity_bad_ref",
        },
    )


# ---------------------------------------------------------------------
# Domain 2: E-commerce orders (a second multi-table domain, different shape)
# ---------------------------------------------------------------------

_MISCATEGORIZED_PRODUCTS = [
    "Organic Bananas", "Fresh Roses Bouquet", "Yoga Mat", "Handmade Soap Bar",
    "Cotton Bath Towel", "Ceramic Coffee Mug", "Leather Wallet", "Wool Scarf",
    "Garden Trowel", "Scented Candle",
]


def generate_ecommerce_orders() -> None:
    n_customers = 40
    customers = [
        {"id": str(i), "name": f"Customer {i}", "country": ["US", "UK", "IN", "DE", "CA"][i % 5]}
        for i in range(1, n_customers + 1)
    ]
    _write_csv("customers", ["id", "name", "country"], customers)

    def clean_row(i: int) -> dict:
        customer_id = (i % n_customers) + 1
        return {
            "id": str(i),
            "customer_id": str(customer_id),
            "confirmation_email": f"order{i}@buyer{i}.com",
            "product_name": f"Wireless Gadget Model {i % 20}",
            "product_category": "Electronics",
            "amount": str(20 + (i * 13) % 480),
            "order_date": "2026-02-10",
        }

    rows: list[dict] = []
    categories: dict[str, list[int]] = {
        "completeness_null": [],
        "uniqueness_duplicate": [],
        "validity_format": [],
        "consistency_outlier": [],
        "referential_integrity_bad_ref": [],
        "semantic_mismatch": [],
    }

    for i in range(90):
        rows.append(clean_row(i))

    for i in range(90, 100):
        r = clean_row(i)
        r["product_name"] = ""
        rows.append(r)
        categories["completeness_null"].append(i)

    for pair in range(3):
        base = clean_row(9000 + pair)
        idx_a, idx_b = 100 + pair * 2, 100 + pair * 2 + 1
        rows.append(dict(base))
        rows.append(dict(base))
        categories["uniqueness_duplicate"].extend([idx_a, idx_b])

    for i in range(106, 116):
        r = clean_row(i)
        if i % 2 == 0:
            r["confirmation_email"] = "bad-email-format"
        else:
            r["order_date"] = "not-a-date"
        rows.append(r)
        categories["validity_format"].append(i)

    for i in range(116, 121):
        r = clean_row(i)
        r["amount"] = str(80_000 + i * 5_000)
        rows.append(r)
        categories["consistency_outlier"].append(i)

    for i in range(121, 128):
        r = clean_row(i)
        r["customer_id"] = "9999"
        rows.append(r)
        categories["referential_integrity_bad_ref"].append(i)

    for offset, i in enumerate(range(128, 138)):
        r = clean_row(i)
        r["product_name"] = _MISCATEGORIZED_PRODUCTS[offset % len(_MISCATEGORIZED_PRODUCTS)]
        rows.append(r)
        categories["semantic_mismatch"].append(i)

    for i in range(138, 150):
        rows.append(clean_row(i))

    assert len(rows) == 150, f"expected 150 rows, got {len(rows)}"
    _write_csv(
        "orders",
        ["id", "customer_id", "confirmation_email", "product_name", "product_category", "amount", "order_date"],
        rows,
    )
    _write_ground_truth(
        "ecommerce_orders", "orders", ["customers"], len(rows), categories,
        deterministic_categories={
            "completeness_null", "uniqueness_duplicate", "validity_format",
            "consistency_outlier", "referential_integrity_bad_ref",
        },
    )


# ---------------------------------------------------------------------
# Domain 3: HR employees (single table — no FK-shaped column at all)
# ---------------------------------------------------------------------

_NON_ENGINEERING_TITLES = [
    "Sales Executive", "Marketing Manager", "HR Coordinator", "Staff Accountant",
    "Customer Support Rep", "Warehouse Associate", "Graphic Designer",
    "Legal Counsel", "Corporate Recruiter", "Office Manager",
]


def generate_hr_employees() -> None:
    def clean_row(i: int) -> dict:
        return {
            "id": str(i),
            "full_name": f"Employee {i}",
            "email": f"emp{i}@company.example",
            "job_title": ["Software Engineer", "Backend Developer", "QA Engineer", "DevOps Engineer"][i % 4],
            "department": "Engineering",
            "hire_date": "2025-06-01",
            "salary": str(55_000 + (i * 211) % 65_000),
        }

    rows: list[dict] = []
    categories: dict[str, list[int]] = {
        "completeness_null": [],
        "uniqueness_duplicate": [],
        "validity_format": [],
        "consistency_outlier": [],
        "semantic_mismatch": [],
    }

    for i in range(90):
        rows.append(clean_row(i))

    for i in range(90, 100):
        r = clean_row(i)
        r["email"] = ""
        rows.append(r)
        categories["completeness_null"].append(i)

    for pair in range(3):
        base = clean_row(9000 + pair)
        idx_a, idx_b = 100 + pair * 2, 100 + pair * 2 + 1
        rows.append(dict(base))
        rows.append(dict(base))
        categories["uniqueness_duplicate"].extend([idx_a, idx_b])

    for i in range(106, 116):
        r = clean_row(i)
        if i % 2 == 0:
            r["email"] = "nobody@nowhere"
        else:
            r["hire_date"] = "32/13/2025"
        rows.append(r)
        categories["validity_format"].append(i)

    for i in range(116, 121):
        r = clean_row(i)
        r["salary"] = str(2_000_000 + i * 10_000)
        rows.append(r)
        categories["consistency_outlier"].append(i)

    for offset, i in enumerate(range(121, 131)):
        r = clean_row(i)
        r["job_title"] = _NON_ENGINEERING_TITLES[offset % len(_NON_ENGINEERING_TITLES)]
        rows.append(r)
        categories["semantic_mismatch"].append(i)

    for i in range(131, 143):
        rows.append(clean_row(i))

    assert len(rows) == 143, f"expected 143 rows, got {len(rows)}"
    _write_csv(
        "employees",
        ["id", "full_name", "email", "job_title", "department", "hire_date", "salary"],
        rows,
    )
    _write_ground_truth(
        "hr_employees", "employees", [], len(rows), categories,
        deterministic_categories={
            "completeness_null", "uniqueness_duplicate", "validity_format", "consistency_outlier",
        },
    )


if __name__ == "__main__":
    generate_crm_leads()
    generate_ecommerce_orders()
    generate_hr_employees()
    print(f"Datasets written to {OUT_DIR}/")
    for f in sorted(OUT_DIR.glob("*_ground_truth.json")):
        data = json.loads(f.read_text())
        print(
            f"  {data['dataset']}: {data['total_rows']} rows, "
            f"{len(data['all_issue_rows'])} planted issues "
            f"({len(data['deterministic_rows'])} deterministic, "
            f"{len(data['semantic_only_rows'])} semantic-only), "
            f"{len(data['clean_rows'])} clean"
        )
