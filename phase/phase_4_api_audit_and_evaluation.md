# Phase 4: API, Audit Logging, Evaluation Suite & Benchmark Report

## 1. Goal & Objectives
Unify all auditor components into a clean, local-first FastAPI service, implement comprehensive audit logging, build the benchmark evaluation harness, and measure empirical performance across baselines on a frozen test suite.

---

## 2. Key Deliverables & Modules

### A. API Layer & Answer Builder (`src/sql_auditor/api.py`, `src/sql_auditor/answer_builder.py`)
- **FastAPI Service**:
  - `POST /ask`: Accepts natural-language question, runs full pipeline, and returns structured result.
  - `GET /health`: Healthcheck reporting database and knowledge bundle status.
- **Answer Structure (`answer_builder.py`)**:
  - Direct answer summary.
  - Executed SQL query.
  - Result rows (subject to row caps).
  - Cited rule IDs and versions applied.
  - Validation & audit trail breakdown.

### B. Audit Trail Logger (`src/sql_auditor/audit_log.py`)
- Logs every request and response to a local SQLite table or JSONL file.
- Captures:
  - Request ID & timestamp.
  - Original question.
  - Retrieved rule IDs and versions.
  - Candidate SQL vs. Final Executed SQL.
  - Guardrail and audit outcomes (pass/fail + reasons).
  - Execution runtime and row count.
  - Ensures no sensitive tokens or stack traces are stored.

### C. Evaluation Suite & Benchmark Comparison (`tests/evaluation/`)
- **Test Set (`tests/evaluation/benchmark_dataset.json`)**:
  - 50–100 hand-verified synthetic questions with gold SQL / expected results.
  - Categories:
    - Direct queries (simple filters, joins).
    - Metric queries requiring explicit business rules (departmental spend, fiscal year).
    - **Rule-trap queries**: Valid, executable SQL that silently violates a business rule.
    - Adversarial attack queries and unsupported/ambiguous requests.
- **Benchmark Configurations**:
  - **Configuration A**: Baseline (Question + Schema only $\rightarrow$ LLM $\rightarrow$ Exec).
  - **Configuration B**: Baseline + Retrieval (Question + Schema + Rules in prompt $\rightarrow$ LLM $\rightarrow$ Exec, no audit).
  - **Configuration C**: Proposed System (Question + Schema + Rules $\rightarrow$ Guardrails $\rightarrow$ Rule Audit $\rightarrow$ Exec).
- **Metrics Computed**:
  - Execution accuracy (exact result match on SQLite).
  - Business-rule compliance rate.
  - Unsafe query rejection rate.
  - False rejection rate.
  - End-to-end latency.

### D. Documentation & Polish
- Update `README.md` with installation, running instructions, architecture diagram, and local quickstart.
- Write `docs/architecture.md`, `docs/threat_model.md`, and `docs/evaluation.md` with measured results.

---

## 3. Testing & Verification

- **End-to-End API Integration Tests (`tests/integration/test_api.py`)**:
  - Test `/ask` endpoint for successful query, rule violation rejection, and syntax safety rejections.
- **Audit Logging Tests (`tests/unit/test_audit_log.py`)**:
  - Verifies structured logs are stored correctly with all rule citations and check results.
- **Evaluation Benchmark Runner (`tests/evaluation/run_benchmark.py`)**:
  - Executes automated evaluation across configurations A, B, and C, generating a metrics summary.

---

## 4. Exit Criteria
- [x] FastAPI `/ask` and `/health` endpoints functional and fully typed.
- [x] Every request logs a complete, auditable trace with rule IDs and check statuses.
- [x] Benchmark harness runs across Configurations A, B, and C with measurable differences recorded.
- [x] Complete documentation with clear steps to reproduce results locally.
