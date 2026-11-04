# System Architecture & Design Specification

## Overview

**Policy-Aware SQL Auditor** is a local-first, deterministic text-to-SQL compliance and safety engine. Unlike conventional text-to-SQL frameworks that rely purely on LLM prompt instructions or shallow keyword checks, this system implements an independent, deterministic AST audit layer that enforces versioned business definitions (OKF concepts) and multi-layered database guardrails before queries are executed.

```
                           [ User Natural Language Question ]
                                           │
                                           ▼
                                ┌──────────────────────┐
                                │    Intent Router     │
                                └──────────┬───────────┘
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   │ (Ambiguous/Unsupported)                       │ (Metric/Entity Question)
                   ▼                                               ▼
         [ Early Clarification / Exit ]                 ┌──────────────────────┐
                                                        │    BM25 Retriever    │
                                                        └──────────┬───────────┘
                                                                   │ (Top Concepts & Policies)
                                                                   ▼
                                                        ┌──────────────────────┐
                                                        │    SQL Generator     │
                                                        └──────────┬───────────┘
                                                                   │ (Candidate SQL)
                                                                   ▼
                                                        ┌──────────────────────┐
                                                        │  SQLGlot Guardrails  │
                                                        └──────────┬───────────┘
                                                                   │ (Safe AST: Single SELECT)
                                                                   ▼
                                            ┌──────────────────────────────────────────────┐
                                            │      Deterministic Rule-Compliance Auditor   │
                                            └──────────────────────┬───────────────────────┘
                                                                   │
                                       ┌───────────────────────────┴───────────────────────────┐
                                       │ (FAIL: Missing Filter / Forbidden Substitute)         │ (PASS: All Rules Met)
                                       ▼                                                       ▼
                            ┌──────────────────────┐                               ┌──────────────────────┐
                            │ Revise Loop (1x Max) │                               │  Safe Executor (RO)  │
                            └──────────────────────┘                               └──────────┬───────────┘
                                       │                                                       │
                                       │ (Persistent Failure)                                  ▼
                                       ▼                                            ┌──────────────────────┐
                              [ Fail-Closed Abort ]                                 │  Audit Log & Answer  │
                                                                                    └──────────────────────┘
```

---

## Core Subsystems

### 1. Schema Inspector (`src/sql_auditor/schema_inspector.py`)
- Connects to SQLite and inspects table schemas, column names, data types, primary keys, and foreign keys.
- Exposes an in-memory `DatabaseSchema` catalog for AST allowlist checking and prompt generation.

### 2. OKF Knowledge Bundle & Loader (`knowledge/`, `src/sql_auditor/knowledge_loader.py`)
- Formats business definitions as versioned Markdown files with YAML frontmatter.
- Each concept specifies:
  - `id` & `version` (e.g. `metric.departmental_spend@v1`).
  - `required_filters`: Mandatory predicates (e.g. `expenses.status = 'approved'`).
  - `forbidden_substitutes`: Prohibited shortcut columns (e.g. `customers.is_active` for active customer definition).
  - `required_joins`: Structural entity relationships.
- Strongly typed and validated against live SQLite schema upon loading.

### 3. Lexical Retrieval & Intent Router (`src/sql_auditor/retrieval.py`, `src/sql_auditor/router.py`)
- **Intent Router**: Identifies question intent (`metric_query`, `policy_check`, `ambiguous`, `unsupported`). Intercepts broad or underspecified inputs early to request clarification.
- **BM25 Lexical Retriever**: Zero-cost, pure-Python Okapi BM25 engine. Ranks concepts by title, description, and tags, expanding related compliance policies without external embedding API dependencies.

### 4. Deterministic SQL Guardrails (`src/sql_auditor/sql_guardrails.py`)
- SQLGlot AST validation enforcing:
  1. Exactly one SQL statement (rejects multiple semicolons / stacked queries).
  2. Strict `SELECT`-only execution (blocks DDL `CREATE`/`DROP`/`ALTER`, DML `INSERT`/`UPDATE`/`DELETE`, administrative commands `PRAGMA`/`ATTACH`/`VACUUM`, and mutating CTEs).
  3. Live schema allowlisting (blocks unknown or hallucinated tables and columns).
  4. Disallowed system functions (`load_extension`, `writefile`, etc.).

### 5. Deterministic Rule-Compliance Auditor (`src/sql_auditor/rule_auditor.py`)
- Translates SQL AST expressions into canonical conditions across `WHERE` and `JOIN ... ON` clauses.
- Normalizes predicates (e.g. `e.status = 'approved'`, `e.status IN ('approved')`, symmetric equality, date functions).
- Audits required filters, date boundaries, and forbidden substitutes.

### 6. Revise-or-Reject Control Loop & Pipeline (`src/sql_auditor/pipeline.py`)
- Feeds diagnostic violation errors back to generator on first failure.
- Permits exactly one revision attempt. If the revised query still fails compliance checks, the pipeline aborts fail-closed. Non-compliant SQL is never sent to the database.

### 7. Safe Read-Only Executor & Audit Logger (`src/sql_auditor/executor.py`, `src/sql_auditor/audit_log.py`)
- Executes verified queries with `mode=ro` (read-only SQLite URI), opcode-based wall-clock timeouts, and row truncation caps.
- Logs full diagnostic audit records (timestamps, rule IDs, candidate vs. final SQL, execution time, and check statuses) into SQLite.

