# Phase 1: Data, Schema Inspection & Deterministic SQL Guardrails

## 1. Goal & Objectives
Establish the safe, deterministic foundational layer of the Policy-Aware SQL Auditor. Ensure the synthetic database is established, the live schema can be inspected programmatically, and strict SQL AST guardrails prevent any unsafe, non-SELECT, multi-statement, or schema-violating queries from ever executing.

---

## 2. Key Deliverables & Modules

### A. Synthetic Database & Schema Inspector
- **Synthetic Data**: Maintain and expand `data/seed_synthetic_data.py` (generating `data/auditor.db`) with trap rows (pending/rejected expenses, multiple fiscal years, edge dates).
- **`src/sql_auditor/config.py`**: Centralized application settings (paths, query timeout, max rows returned, allowed dialects).
- **`src/sql_auditor/schema_inspector.py`**:
  - Connects to SQLite and reads live tables, columns, primary keys, and foreign keys.
  - Builds an in-memory schema catalog used by AST validators and prompts.

### B. Deterministic Guardrails (`src/sql_auditor/sql_guardrails.py`)
- Uses **SQLGlot** to parse candidate SQL into an AST.
- **Enforcement checks**:
  1. **Single-statement check**: Rejects multiple statements separated by semicolons.
  2. **Read-only SELECT-only**: Rejects DDL (`CREATE`, `DROP`, `ALTER`), DML (`INSERT`, `UPDATE`, `DELETE`), administrative commands (`PRAGMA` modifications, `ATTACH`), and CTEs that conceal mutations.
  3. **Schema Allowlist**: Compares every referenced table and column in the AST against `schema_inspector` output. Unknown or hallucinated identifiers fail immediately.
  4. **Disallowed Functions**: Blocks system or execution functions that could compromise the runtime.
- **Fail Closed**: Any unparseable or ambiguous statement is immediately rejected.

### C. Safe Read-Only Executor (`src/sql_auditor/executor.py`)
- Executes verified queries against SQLite with `mode=ro` (read-only URI).
- Applies safety controls:
  - Enforces `PRAGMA foreign_keys = ON;`.
  - Wall-clock timeout limit (e.g., 2.0s).
  - Row cap (e.g., max 100 rows returned).
  - Clean error formatting without leaking stack traces.

---

## 3. Testing & Verification

- **Unit Tests (`tests/unit/test_guardrails.py`)**:
  - Valid `SELECT` statements with joins and aggregations pass.
  - Multi-statement queries rejected.
  - Mutation statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`) rejected.
  - Non-existent table/column names rejected.
- **Safety Attack Tests (`tests/safety/test_attack_queries.py`)**:
  - 15+ deliberate SQL injection, commenting, subquery bypass, and DDL payload attempts.
- **Executor Tests (`tests/unit/test_executor.py`)**:
  - Read-only queries execute and return dictionary/tuple records.
  - Write attempts at the SQLite level trigger errors.
  - Row truncation and timeout mechanics trigger properly.

---

## 4. Exit Criteria
- [x] Schema inspector extracts live schema catalog accurately.
- [x] SQLGlot guardrails reject all 15+ attack/disallowed query variations.
- [x] Read-only executor runs valid queries and blocks write attempts at the connection layer.
- [x] All unit and safety tests pass cleanly via `pytest`.
