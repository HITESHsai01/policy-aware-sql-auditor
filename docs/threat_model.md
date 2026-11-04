# Threat Model & Security Mitigations

## Security Philosophy: Defense-in-Depth

The Policy-Aware SQL Auditor does **not** rely on LLMs or prompt instructions for safety. Safety is enforced deterministically by layers of verified application code and SQLite sandbox constraints. No LLM generation can bypass these safety barriers.

---

## Threat Matrix

| Threat / Attack Vector | Vulnerability Description | Mitigation Layer | Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **Stacked SQL Injections** | Multiple statements separated by semicolons (e.g. `SELECT 1; DROP TABLE expenses;`). | Deterministic Guardrail | SQLGlot single-statement AST check and pre-parse semicolon injection detector. |
| **Data Destruction (DDL/DML)** | Queries modifying tables (`DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `INSERT`, `UPDATE`, `DELETE`). | AST Guardrail & Connection Layer | SQLGlot rejects any non-SELECT AST node; SQLite connection opened strictly with URI `mode=ro`. |
| **Mutating CTE Evasion** | Disguising DML inside Common Table Expressions (`WITH x AS (DELETE ... RETURNING *) SELECT * FROM x`). | AST Guardrail | AST recursive node walk ensures NO `Insert`, `Update`, `Delete`, or `Command` nodes exist in any subquery or CTE. |
| **Schema Hallucination & Reconnaissance** | Probing or accessing uncertified or sensitive tables (`SELECT * FROM sqlite_master;` or `admin_users`). | Schema Allowlist Guardrail | Every table and column identifier in the AST must match the reflected live `DatabaseSchema`. |
| **Code Execution Exploits** | Invoking dangerous SQLite functions (`load_extension('shell.dll')`, `writefile()`, `readfile()`). | AST Function Guardrail | Disallowed function allowlist blocks all high-risk execution functions fail-closed. |
| **Resource Exhaustion (DoS)** | Infinite recursive CTEs or unindexed expensive Cartesian products. | Executor Safety Controls | Wall-clock timeout enforced via SQLite opcode progress handler callback (`conn.set_progress_handler`). |
| **Memory Exhaustion (OOM)** | Query returning millions of rows. | Executor Row Cap | Result fetch is capped at `max_rows` (default 100), flagging truncation cleanly. |
| **Business Rule Violation** | Valid SQL that silently violates company policy (e.g. `is_active=1` or spend including rejected claims). | Semantic Rule Auditor | AST condition extraction verifies required filters and blocks forbidden substitutes deterministically. |
| **Audit Log Tampering & Secret Leakage** | Injecting secrets or dumping stack traces into audit logs. | Sanitized Logger | Stack traces are caught and sanitized; only structured diagnostic codes and SQL strings are recorded. |

---

## Fail-Closed Guarantee

If any check cannot definitively verify that a candidate query is compliant, safe, and read-only, execution is **strictly refused**:

$$\text{Allow Execution} \iff (\text{Guardrails} = \text{PASS}) \land (\text{Rule Compliance} = \text{PASS})$$

