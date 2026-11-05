# Policy-Aware SQL Auditor

A policy-aware SQL auditing and retrieval engine designed to analyze, validate, and audit SQL queries against defined compliance rules, business policies, and schema constraints before execution.

---

## Key Differentiator

Traditional text-to-SQL tools only check syntactic validity or general read-only safety. However, a query can run without errors and still return **plausible, wrong answers** (e.g., computing departmental spend without filtering out rejected claims, or counting active customers by checking legacy flags instead of trailing orders).

**Policy-Aware SQL Auditor** solves this by:
1. Encoding business definitions into versioned **Open Knowledge Format (OKF)** concepts.
2. Deterministically parsing candidate SQL ASTs via **SQLGlot** to verify that mandatory business rules, required predicates, and relationship joins are strictly satisfied.
3. Providing a controlled **Revise-or-Reject loop** that feeds exact diagnostic messages back to the generator, failing closed if compliance cannot be guaranteed.

---

## Architecture Overview

```
[ User Question ] ──▶ [ Intent Router ] ──▶ [ BM25 Retriever ] ──▶ [ SQL Generator ]
                                                                           │
                                                                           ▼
[ Safe Read-Only Execution ] ◀── [ Deterministic Rule Audit ] ◀── [ SQLGlot Guardrails ]
           │                                │ (On Failure)
           ▼                                ▼
   [ SQLite Audit Log ]           [ Revise Loop (1x) ] ──▶ [ Fail-Closed Abort ]
```

---

## Implementation Phases (100% Completed)

### Phase 1: Data, Schema Inspection & Deterministic SQL Guardrails
- **Synthetic Database & Seeding** (`data/seed_synthetic_data.py`, `src/sql_auditor/schema_inspector.py`):
  - Deterministic SQLite database (`data/auditor.db`) with `departments`, `budgets`, `expenses`, `customers`, and `orders`.
  - Reflects tables, columns, primary keys, and foreign keys into an in-memory schema catalog.
- **Deterministic SQL Guardrails** (`src/sql_auditor/sql_guardrails.py`):
  - SQLGlot AST parsing with fail-closed safety semantics.
  - Enforces single-statement queries (blocks stacked semicolons/injections).
  - Enforces SELECT-only queries (blocks DDL, DML, PRAGMA, administrative operations, mutating CTEs).
  - Schema allowlisting (strictly rejects unknown/hallucinated tables and columns).
  - Blocks high-risk system functions (`load_extension`, `writefile`, etc.).
- **Safe Read-Only Executor** (`src/sql_auditor/executor.py`):
  - Executes verified queries against SQLite with `mode=ro` (read-only URI).
  - Enforces foreign key constraints, wall-clock timeout limits, and row-count truncation caps.

### Phase 2: OKF Knowledge Bundle, Loader & Lexical Retrieval
- **OKF Concept Bundle** (`knowledge/`):
  - Versioned Open Knowledge Format concept definitions with YAML frontmatter.
  - **Metrics**: `departmental_spend` (approved spend in fiscal year), `active_customer` (completed orders in trailing 90 days; forbids legacy `is_active` substitute).
  - **Policies**: `expense_reimbursement` (approval requirement), `fiscal_year` (calendar boundary standard).
  - **Tables**: `departments`, `budgets`, `expenses`, `customers`, `orders`.
- **Knowledge Loader & Validator** (`src/sql_auditor/knowledge_loader.py`):
  - Reads and validates concepts against the live SQLite database schema.
  - Verifies that cross-concept references resolve and filter models parse cleanly.
- **BM25 Lexical Retriever** (`src/sql_auditor/retrieval.py`):
  - Zero-cost, pure-Python Okapi BM25 search over titles, tags, descriptions, and definitions.
  - Automatic expansion of related policies and metrics.
- **Intent Router** (`src/sql_auditor/router.py`):
  - Classifies questions into `metric_query`, `policy_check`, `ambiguous`, or `unsupported`.
  - Extracts entities (fiscal years, departments, statuses) and generates clarifying prompts for underspecified requests.

### Phase 3: SQL Generation, Rule-Compliance Auditor & Revise Loop
- **Prompt Grounding & SQL Generator** (`src/sql_auditor/sql_generator.py`):
  - Grounded prompts with live schema, business definitions, and previous revision feedback.
  - Pluggable backends: `OllamaBackend` (local LLMs: Llama 3, Qwen-Coder, Mistral) and `MockGeneratorBackend` (deterministic testing & offline evaluation).
  - Robust code-fence extraction for clean candidate SQL.
- **Deterministic Rule-Compliance Auditor** (`src/sql_auditor/rule_auditor.py`):
  - Resolves table aliases to canonical schema tables.
  - Normalizes predicates (`status = 'approved'`, `status IN ('approved')`, symmetric equality, date functions `strftime`).
  - Audits required equality filters, fiscal year date bounds, and trailing time windows.
  - Detects and rejects forbidden substitute columns (e.g. `customers.is_active` for active customers).
- **Revise-or-Reject Control Loop & Pipeline** (`src/sql_auditor/pipeline.py`):
  - End-to-end orchestration: Intent $\rightarrow$ Retrieval $\rightarrow$ Generation $\rightarrow$ Guardrails $\rightarrow$ Rule Audit $\rightarrow$ Revise Loop $\rightarrow$ Execution.
  - On rule violation, triggers exactly 1 revision attempt with specific diagnostic error feedback.
  - Fails closed: queries with unresolved violations or safety failures are permanently rejected and never reach the database.

### Phase 4: API & Audit Logging
- **FastAPI REST Service** (`src/sql_auditor/api.py`):
  - `POST /ask`: Evaluates questions, generates compliant SQL, audits rules, and executes read-only.
  - `GET /health`: Healthcheck reporting database and concept status.
  - `GET /audit-logs`: Returns recent structured audit logs.
  - `GET /rules`: Returns loaded OKF concept rules and definitions.
- **Answer Builder** (`src/sql_auditor/answer_builder.py`):
  - Constructs consumer responses with natural language answers, executed SQL, result rows, and cited rule versions.
- **Persistent Audit Logger** (`src/sql_auditor/audit_log.py`):
  - Logs complete request traces into an indexed SQLite audit table (`audit_logs`) without leaking secrets.

### Phase 5: Evaluation & Benchmarking
- **Separation of Candidates and Ground Truth** (`tests/evaluation/mock_candidates.json`):
  - Strict elimination of test contamination: candidate queries generated independently of gold ground truth.
- **Independent Expected-Result Fixtures** (`tests/evaluation/benchmark_dataset.json`):
  - 50 frozen benchmark cases with precomputed multiset execution fixtures across 6 distinct categories.
- **Benchmark Evaluation Harness & Metrics** (`tests/evaluation/run_benchmark.py`, `tests/evaluation/eval_utils.py`):
  - Evaluates Configuration A (Baseline), Configuration B (Prompt Grounding + AST Guardrails), and Configuration C (Full Proposed Auditor).
  - Robust multiset cell-normalized row comparison, zero-division safe metrics, revision effectiveness tracking, and CLI options (`--mode {mock,real}`).

---

## Empirical Benchmark Results

Evaluated across the 50 frozen test questions in `tests/evaluation/benchmark_dataset.json`:

| Metric | Config A: Baseline | Config B: Baseline + Rules | Config C: Proposed Auditor |
| :--- | :---: | :---: | :---: |
| **Execution Accuracy** | 30.0% (9/30) | 66.7% (20/30) | **96.7% (29/30)** |
| **Business-Rule Compliance Rate** | 0.0% (0/21) | 52.4% (11/21) | **100.0% (21/21)** |
| **Unsafe-Query Rejection Rate** | 100.0% (10/10) | 100.0% (10/10) | **100.0% (10/10)** |
| **False Rejection Rate** | 0.0% (0/20) | 0.0% (0/20) | **0.0% (0/20)** |
| **Overall System Decision Accuracy** | 38.0% (19/50) | 60.0% (30/50) | **98.0% (49/50)** |
| **Revision Success Rate** | N/A | N/A | **90.0% (9/10 repaired, 1 blocked)** |
| **Average Latency (ms)** | 0.96 ms | 1.45 ms | **2.79 ms** |

See [`docs/evaluation.md`](docs/evaluation.md) for full analysis and details.

---

## Quickstart

### 1. Seed the Database
```powershell
python data/seed_synthetic_data.py
```

### 2. Run the Test Suite (113 passing tests)
```powershell
python -m pytest -v tests
```

### 3. Run the Evaluation Benchmark
```powershell
$env:PYTHONPATH="src;."
python tests/evaluation/run_benchmark.py
```

### 4. Start the FastAPI Service
```powershell
uvicorn sql_auditor.api:app --host 127.0.0.1 --port 8000 --reload
```

Interactive OpenAPI docs will be available at: `http://127.0.0.1:8000/docs`

---

## Documentation Links
- [System Architecture Specification](docs/architecture.md)
- [Threat Model & Defense Matrix](docs/threat_model.md)
- [Evaluation & Benchmark Report](docs/evaluation.md)
