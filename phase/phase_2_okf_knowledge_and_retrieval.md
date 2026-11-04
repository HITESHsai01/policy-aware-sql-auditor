# Phase 2: OKF Knowledge Bundle, Loader & Lexical Retrieval

## 1. Goal & Objectives
Structure all business definitions, policies, and table documentation as versioned Open Knowledge Format (OKF) concept files. Implement a robust loader and a local, zero-cost BM25 lexical retriever to fetch relevant rules and schema context for any incoming user question.

---

## 2. Key Deliverables & Modules

### A. OKF Knowledge Bundle Structure (`knowledge/`)
Establish standard OKF concept markdown files with structured YAML front matter and explicit machine-readable constraints:
```text
knowledge/
├── index.md
├── metrics/
│   ├── departmental_spend.md
│   └── active_customer.md
├── policies/
│   ├── expense_reimbursement.md
│   └── fiscal_year.md
└── tables/
    ├── departments.md
    ├── budgets.md
    ├── expenses.md
    ├── customers.md
    └── orders.md
```
- Each concept file includes:
  - `id`: Unique stable identifier (e.g., `metric.departmental_spend`).
  - `version`: Version number / ISO timestamp.
  - `title`, `description`, `tags`.
  - Structured `# Required filters` (column, operator, value, range requirements) for deterministic checking.
  - Linked tables and policies.

### B. Knowledge Loader & Validator (`src/sql_auditor/knowledge_loader.py`)
- Reads the `knowledge/` bundle.
- Validates that:
  - Every markdown concept parses correctly.
  - Every referenced table and column exists in the live schema (via `schema_inspector`).
  - Every relative link between concepts resolves cleanly.
  - Machine-readable filter definitions parse into strongly-typed Python dataclasses/Pydantic models.

### C. Lexical Retrieval & Intent Router (`src/sql_auditor/retrieval.py` & `src/sql_auditor/router.py`)
- **Router (`router.py`)**:
  - Classifies user questions into intent categories (`metric_query`, `policy_check`, `ambiguous`, `unsupported`).
  - Detects ambiguous or unanswerable queries early to prompt for clarification.
- **Retriever (`retrieval.py`)**:
  - Pure Python BM25 / token-overlap lexical search over concept titles, descriptions, tags, and definitions.
  - Returns top-$k$ relevant business rules and table definitions without requiring external embedding models or paid APIs.

---

## 3. Testing & Verification

- **Loader Integrity Tests (`tests/unit/test_knowledge_loader.py`)**:
  - Validates that all concept files parse and contain required fields.
  - Fails if a rule references a non-existent table or column.
- **Retrieval Accuracy Tests (`tests/unit/test_retrieval.py`)**:
  - Questions about "department spend in 2024" reliably retrieve `metric.departmental_spend` and `policy.fiscal_year`.
  - Questions about "active customers" reliably retrieve `metric.active_customer`.
- **Router Tests (`tests/unit/test_router.py`)**:
  - Ambiguous queries are flagged as requiring clarification.

---

## 4. Exit Criteria
- [x] Knowledge bundle fully formatted with metrics, policies, and table descriptions.
- [x] Loader passes validation against the live database schema.
- [x] BM25 retrieval returns the correct rules and schema items for benchmark question sets.
- [x] Router correctly classifies intent and flags ambiguous inputs.
