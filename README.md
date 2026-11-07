# Policy-Aware SQL Auditor

> **Deterministic SQL governance, semantic policy auditing, and AST security guardrails for enterprise Text-to-SQL generation.**

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SQL POLICY AUDITOR   [READ-ONLY AIRGAP]   [CORE V0.1.0]                               │
│  DATABASE: auditor.db (6 tables)  POLICIES: 10 OKF rules  PARSER: SQLGlot AST (SQLite) │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  [1. INTENT ROUTER: PASS] ──▶ [2. AST GUARDRAILS: PASS] ──▶ [3. OKF POLICY AUDIT: PASS]│
│                                                                                        │
│  [APPROVED - FULL COMPLIANCE] Query satisfied all deterministic AST guardrails         │
│                                                                                        │
│  SQL COMPILATION & REVISION                    COMPLIANCE & AST VERIFICATION MATRIX    │
│  SELECT d.name, SUM(e.amount)                  1. AST Guardrail Verification:          │
│  FROM departments AS d                           [PASS] Statement Type : SELECT-only   │
│  JOIN expenses AS e ON d.id = e.department_id    [PASS] Schema Ground  : Verified cata │
│  WHERE e.status = 'approved'                     [PASS] Dangerous Funcs: 0 detected    │
│    AND e.expense_date BETWEEN '2025-01-01'     2. Retrieved Governing Policies:        │
│                           AND '2025-12-31'       • policy.expense_reimbursement@v1     │
│  GROUP BY d.name;                                • metric.departmental_spend@v1        │
│                                                  • policy.fiscal_year@v1               │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## The Core Problem

Traditional text-to-SQL systems only verify syntactic validity or basic read-only access. However, a query can run completely error-free and still return **plausible, legally hazardous, or economically incorrect answers**:
- Aggregating departmental spend without filtering out rejected or pending expense claims.
- Calculating "active customers" by checking legacy boolean flags instead of verified trailing transaction windows.
- Breaching fiscal year calendar boundaries by querying unbounded date ranges.

**Policy-Aware SQL Auditor** acts as an air-gapped governance layer between the LLM and the relational database, enforcing deterministic compliance rules encoded in versioned **Open Knowledge Format (OKF)** bundles.

---

## Key Capabilities

1. **Deterministic AST Policy Auditing**: Uses [SQLGlot](https://github.com/tobymao/sqlglot) to deterministically parse candidate SQL ASTs. Audits required equality predicates, join paths, fiscal date ranges, and strictly forbids unauthorized/legacy columns.
2. **Hardened AST Security Guardrails**: Enforces single-statement SELECT-only queries, strips comments, validates schema against a strict catalog allowlist, and blocks injection attacks, administrative PRAGMAs, and mutating CTEs.
3. **Revise-or-Reject Control Loop**: If a candidate query violates a policy invariant, the auditor produces targeted AST diagnostics and feeds them back into the generator for automatic self-correction. If compliance cannot be guaranteed within budget, the query is rejected (fail-closed).
4. **Multi-Engine Generator Support**: Seamlessly switch between **Google Gemini API** (cloud LLM), **Ollama** (local offline models like Llama 3 / Qwen-Coder), and a **Deterministic Simulator** (zero-network offline evaluation).
5. **Interactive Governance Dashboard**: Built with Streamlit, providing real-time AST verification matrix inspection, SQL compilation diffs, policy justifications, audit ledger history, and query results.
6. **Immutable Audit Trail**: Persists structured audit traces into an indexed SQLite audit table for SOC2/compliance reviews.

---

## Architecture & Control Flow

```
[ Natural Language Question ]
              │
              ▼
    [ 1. Intent Router ] ──────────── (Rejects Ambiguous / Unsupported Queries)
              │
              ▼
    [ 2. BM25 Knowledge Retrieval ] ── (Fetches Relevant OKF Business Rules & Tables)
              │
              ▼
    [ 3. SQL Generator ] ───────────── (Prompt Grounded: Gemini, Ollama, or Mock)
              │
              ▼
    [ 4. SQLGlot AST Guardrails ] ──── (Rejects DDL, DML, Injections, Unknown Tables)
              │
              ▼
    [ 5. Deterministic Rule Audit ] ── (Checks Required Filters, Joins & Prohibitions)
              │
     ┌────────┴────────┐
  [Passed]          [Failed]
     │                 │
     │                 ▼
     │       [ Revise Loop (1x) ] ──▶ Diagnostic Feedback ──▶ [ SQL Generator ]
     │                 │ (If still invalid)
     │                 ▼
     │          [ Fail-Closed Rejection ]
     ▼
[ 6. Safe Read-Only Execution ] ── (SQLite `mode=ro`, timeout limits, row caps)
     │
     ▼
[ 7. Governance Audit Log ] & [ Consumer Answer Builder ]
```

---

## Interactive Dashboard

The repository includes a dark-themed Streamlit application providing complete visibility into every stage of the auditing pipeline.

```powershell
streamlit run app.py
```

### Dashboard Features
- **Query Studio**: Test ad-hoc questions or pick preloaded benchmark scenarios from the sidebar.
- **AST & Compliance Matrix**: Live visual indicators showing each AST safety pass, retrieved policies, and invariant checks.
- **SQL Compilation & Revision Artifact**: Side-by-side view of candidate queries and automated repair revisions.
- **Relational Execution Results**: Safe preview of execution rows, column headers, and execution latency.
- **Policy Repository & Schema Dictionary**: Inspect active Open Knowledge Format (OKF) markdown specifications and live table schemas.
- **Audit Ledger**: Searchable historical log of queries, verdicts, execution statuses, and latencies.

| Dashboard View | Description |
| :--- | :--- |
| **Query Studio** | Natural language query prompt input, model selection (Gemini / Ollama / Simulator), temporal horizon controls, and benchmark presets. |
| **AST & Compliance Matrix** | Real-time AST safety pass/fail checks, retrieved OKF policies, and invariant verification verdicts. |
| **SQL Revision Artifact** | Side-by-side view comparing candidate SQL against automatic self-correction repairs. |
| **Execution Results** | Safe read-only preview of executed database rows, column headers, and execution latency in milliseconds. |

---

## Test Suite & Validation

The test suite contains **116 automated tests** testing 100% pure business logic, AST security threat vectors, and self-correction pipelines with **zero external network, server, or UI dependencies**.

### How to Run the Tests

Run the entire test suite with verbose output:

```powershell
pytest -v tests
```
*or via python module syntax:*
```powershell
python -m pytest -v tests
```

To run a specific test suite or module:
```powershell
# Run the 21 SQL AST security and adversarial injection attack tests
pytest tests/safety -v

# Run the revise-or-reject feedback loop integration tests
pytest tests/integration -v

# Run all deterministic rule auditor unit tests
pytest tests/unit/test_rule_auditor.py -v

# Run SQLGlot guardrails tests
pytest tests/unit/test_guardrails.py -v
```

### Test Directory Structure

```text
tests/
├── conftest.py                   # Pytest fixtures, schema setup & knowledge bundle loader
├── safety/
│   └── test_attack_queries.py    # 21 attack vectors: stacked DROP TABLE, DDL/DML, PRAGMA tampering,
│                                 # injection exploits, and unauthorized schema access.
├── integration/
│   └── test_revision_loop.py     # End-to-end revise-or-reject loop: missing filters, join repair,
│                                 # revision feedback handling, and fail-closed exhaustion.
├── unit/
│   ├── test_rule_auditor.py      # Deterministic rule checks (equality predicates, joins, date boundaries, forbidden columns).
│   ├── test_guardrails.py        # SQLGlot AST validation, dialect checks, schema allowlisting, and comment stripping.
│   ├── test_retrieval.py         # BM25 lexical ranking algorithm and policy expansion.
│   ├── test_router.py            # Intent classification (metric query, policy check, catalog search, ambiguous queries).
│   ├── test_sql_generator.py     # Prompt assembly, markdown SQL extraction, and revision feedback grounding.
│   ├── test_executor.py          # Read-only SQLite executor, execution timeout, row truncation, and parameter safety.
│   ├── test_answer_builder.py    # Formatting tabular query results into natural language with policy warnings.
│   ├── test_audit_log.py         # Structured SQLite audit trail recording and schema verification.
│   ├── test_knowledge_loader.py  # Open Knowledge Format (OKF) YAML frontmatter & rule parsing.
│   └── test_benchmark.py         # Evaluation metrics math (execution rate, compliance rate, confusion matrix).
└── evaluation/
    ├── benchmark_dataset.json    # 50 frozen benchmark test scenarios with precomputed golden truth.
    ├── mock_candidates.json      # Offline candidate responses across Config A, B, and C.
    ├── eval_utils.py             # Multiset cell-normalized row comparison and evaluation math.
    └── run_benchmark.py          # Benchmark runner CLI (`--mode {mock,real}`).
```

---

## Empirical Benchmark Results

Evaluated across the 50 frozen test scenarios in `tests/evaluation/benchmark_dataset.json`:

| Metric | Config A: Baseline | Config B: Baseline + Rules | Config C: Proposed Auditor |
| :--- | :---: | :---: | :---: |
| **Execution Accuracy** | 30.0% (9/30) | 66.7% (20/30) | **96.7% (29/30)** |
| **Business-Rule Compliance Rate** | 0.0% (0/21) | 52.4% (11/21) | **100.0% (21/21)** |
| **Unsafe-Query Rejection Rate** | 100.0% (10/10) | 100.0% (10/10) | **100.0% (10/10)** |
| **False Rejection Rate** | 0.0% (0/20) | 0.0% (0/20) | **0.0% (0/20)** |
| **Overall System Decision Accuracy** | 38.0% (19/50) | 60.0% (30/50) | **98.0% (49/50)** |
| **Revision Success Rate** | N/A | N/A | **90.0% (9/10 repaired, 1 blocked)** |
| **Average Latency (ms)** | 0.96 ms | 1.45 ms | **2.79 ms** |

To reproduce the benchmark evaluation:
```powershell
python tests/evaluation/run_benchmark.py --mode mock
```
*(Use `--mode real` to evaluate live LLM calls against your configured Gemini or Ollama backend).*

---

## Quickstart & Installation

### 1. Clone the Repository & Install Dependencies
```powershell
git clone https://github.com/HITESHsai01/policy-aware-sql-auditor.git
cd policy-aware-sql-auditor

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Environment (Optional for Cloud LLMs)
Copy the example environment file and configure your API key if using Google Gemini:
```powershell
copy .env.example .env
```
In `.env`:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```
*(If no API key is provided, you can still run fully offline using the **Deterministic Simulator** or local **Ollama**).*

### 3. Initialize Synthetic Database
```powershell
python data/seed_synthetic_data.py
```

### 4. Run the Test Suite
```powershell
python -m pytest -v tests
```

### 5. Launch the Dashboard
```powershell
streamlit run app.py
```

### 6. Run the REST API Service
```powershell
uvicorn sql_auditor.api:app --host 127.0.0.1 --port 8000 --reload
```
Interactive OpenAPI documentation will be accessible at: `http://127.0.0.1:8000/docs`

---

## Documentation Links
- [System Architecture Specification](docs/architecture.md)
- [Threat Model & Defense Matrix](docs/threat_model.md)
- [Benchmark Evaluation Report](docs/evaluation.md)
