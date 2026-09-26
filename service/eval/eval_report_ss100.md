# DBCaaS Agentic Evaluation Report

## crm_leads

Total rows: 150, planted issues: 48 (38 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 38 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 155.17s): precision 1.0, recall 0.938, F1 0.968 against all 48 planted issues. Semantic-only recall: 0.7 (27 semantic flags raised, 27 verified, 3 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric threshold (correct): "Flag any lead with an amount greater than 100000" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag anything that seems inconsistent with this account's industry" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag leads where the moon_phase field is waning" -> expected `semantic`, got `semantic`

## ecommerce_orders

Total rows: 150, planted issues: 48 (38 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 38 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 140.09s): precision 1.0, recall 0.854, F1 0.921 against all 48 planted issues. Semantic-only recall: 0.3 (10 semantic flags raised, 10 verified, 3 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric comparison (correct): "Flag any order where amount is less than 0" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag orders where the product doesn't match its stated category" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag orders where shipping_carrier is FedEx" -> expected `semantic`, got `semantic`

## hr_employees

Total rows: 143, planted issues: 41 (31 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 31 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 143.16s): precision 1.0, recall 1.0, F1 1.0 against all 41 planted issues. Semantic-only recall: 1.0 (32 semantic flags raised, 32 verified, 3 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric threshold (correct): "Flag any employee with salary greater than 500000" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag anyone whose job title doesn't fit their department" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag employees where the security_clearance field is missing" -> expected `semantic`, got `semantic`
