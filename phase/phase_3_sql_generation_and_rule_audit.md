# Phase 3: SQL Generation, Rule-Compliance Auditor & Revise Loop

## 1. Goal & Objectives
Implement the core differentiator of the project: the **deterministic Rule-Compliance Auditor**. Generate SQL queries using prompt grounding, parse the candidate SQL AST using SQLGlot, verify that all business rule requirements (such as required filters and joins) are satisfied, and provide a single controlled revision loop if a violation is detected.

---

## 2. Key Deliverables & Modules

### A. SQL Generator (`src/sql_auditor/sql_generator.py`)
- Constructs structured prompts containing:
  - User natural-language question.
  - Live schema details (tables, columns, types).
  - Retrieved business rules and metric definitions.
- Pluggable model backend:
  - Local LLM via Ollama (e.g., Llama 3 / Mistral / Qwen-Coder).
  - Mock generator for automated testing and deterministic CI/CD runs.
  - Generates candidate SQL only (never executes directly).

### B. Rule-Compliance Auditor (`src/sql_auditor/rule_auditor.py`)
- Receives candidate SQL and the set of retrieved rules.
- Parses SQL into an AST via **SQLGlot**.
- **Audit Steps**:
  1. **Condition Extraction**: Traverses `WHERE` clauses and `JOIN ... ON` expressions, mapping table aliases back to real table names.
  2. **Predicate Normalization**: Treats equivalent SQL constructs as identical (e.g., `status = 'approved'` and `status IN ('approved')`).
  3. **Required Filter Validation**:
     - Confirms required equality filters (e.g., `expenses.status = 'approved'`).
     - Validates date range expressions (e.g., matching the fiscal year boundaries).
  4. **Required Joins & Prohibited Substitutions**:
     - Ensures required relationship paths are established.
     - Flags forbidden substitutes (e.g., using `customers.is_active` when the business definition mandates 90-day order activity).
- **Audit Output**:
  - `status`: `PASS` or `FAIL`.
  - `rule_ids`: List of evaluated rule IDs with versions.
  - `violations`: Clear diagnostic messages detailing missing filters or forbidden predicates.

### C. Revise-or-Reject Control Loop
- If the candidate SQL passes guardrails and rule audit $\rightarrow$ proceed to execution.
- If rule audit detects a violation $\rightarrow$ trigger **one controlled revision attempt** feeding the exact violation message back to the generator.
- If the revised SQL still fails $\rightarrow$ reject query and refuse execution (fail closed).

---

## 3. Testing & Verification

- **Rule Auditor Tests (`tests/unit/test_rule_auditor.py`)**:
  - Verifies queries with `expenses.status = 'approved'` pass.
  - Verifies queries missing the `status` filter fail with explicit error `missing required filter: expenses.status = 'approved'`.
  - Verifies predicate normalization (equality vs. `IN` clause).
  - Verifies alias resolution in complex joins.
- **Revise Loop Tests (`tests/integration/test_revision_loop.py`)**:
  - Simulates a query missing a required filter; verifies the revised query corrects the filter and passes.
  - Verifies persistent failures reject cleanly without execution.

---

## 4. Exit Criteria
- [x] Rule auditor successfully extracts AST filters and resolves aliases.
- [x] Known rule-violating queries are caught deterministically with structured diagnostic errors.
- [x] Revision loop successfully fixes at least one violation or cleanly aborts.
- [x] No unapproved or rule-violating query ever reaches the executor.
