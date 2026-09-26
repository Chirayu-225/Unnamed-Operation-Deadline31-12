# DBCaaS Agentic Evaluation Report

## crm_leads

Total rows: 150, planted issues: 48 (38 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 38 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 162.91s): precision 1.0, recall 1.0, F1 1.0 against all 48 planted issues. Semantic-only recall: 1.0 (47 semantic flags raised, 47 verified, 4 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric threshold (correct): "Flag any lead with an amount greater than 100000" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag anything that seems inconsistent with this account's industry" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag leads where the moon_phase field is waning" -> expected `semantic`, got `semantic`

## ecommerce_orders

Total rows: 150, planted issues: 48 (38 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 38 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 92.95s): precision 1.0, recall 0.875, F1 0.933 against all 48 planted issues. Semantic-only recall: 0.4 (12 semantic flags raised, 12 verified, 4 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric comparison (correct): "Flag any order where amount is less than 0" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag orders where the product doesn't match its stated category" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag orders where shipping_carrier is FedEx" -> expected `semantic`, got `semantic`

## hr_employees

Total rows: 143, planted issues: 41 (31 deterministic, 10 semantic-only)

**Deterministic baseline** (no LLM): precision 1.0, recall 1.0, F1 1.0 against the 31 deterministically-catchable planted issues.

**Full agentic run** (Groq generator + Gemini verifier, 132.27s): precision 1.0, recall 0.878, F1 0.935 against all 41 planted issues. Semantic-only recall: 0.5 (23 semantic flags raised, 23 verified, 4 reasoning cycle(s) run).

**Custom-instruction battery:**

  - structured: numeric threshold (correct): "Flag any employee with salary greater than 500000" -> expected `structured`, got `structured`
  - semantic: judgment call (correct): "Flag anyone whose job title doesn't fit their department" -> expected `semantic`, got `semantic`
  - semantic: field not in schema, safe fallback (correct): "Flag employees where the security_clearance field is missing" -> expected `semantic`, got `semantic`
