# Policy-Aware SQL Auditor: Project Report

Oct 19, 2026 · @Hitesh

## Executive summary

Policy-Aware SQL Auditor is a local-first text-to-SQL system that checks every AI-written query against versioned business rules, and runs it only if deterministic safety checks also pass.

The core hypothesis: enforcing explicit business rules on the parsed SQL, outside the model, catches queries that are valid and safe but wrong, and does so better than a basic text-to-SQL baseline. This is a hypothesis to test, not a result.

The closest existing work, Datum, already has a multi-agent pipeline, a sqlglot critic and read-only SQLite. It checks safety and schema grounding, not whether a query applies a company's own definitions. That rule-compliance audit is the contribution this project should own.

Status: proposed design. Nothing is implemented and there are no measured results yet.

## Problem and motivation

A query can run without errors and still answer the wrong business question. Two examples from this project's synthetic domain:

- **Active customer.** The table has `customers.is_active`, but the company defines active as at least one completed order in the last 90 days. A query filtering on `is_active = TRUE` runs and returns a plausible, wrong count.
- **Departmental spend.** Spend counts only approved expenses inside the fiscal year. A query that filters on the date range alone includes pending and rejected expenses and overstates every department.

A wrong number that looks right costs more than an error message, because people act on it. Analysts avoid these mistakes by knowing the definitions. Non-technical users and AI tools do not.

The project's answer: store each definition as a versioned rule, retrieve the relevant rules for each question, and check the generated SQL against them deterministically.

## Related work and significant differences

Similar projects exist, and one is close to this design. The overlap figures are my rough estimates from each project's public README or description, not measurements, and I have not read their source code.

| Project | Purpose | Overlap (est.) | Significant difference from this project |
| --- | --- | --- | --- |
| [Datum](https://github.com/malharinamdar/datum) | Grounds an LLM on a governed semantic layer to answer questions over SQLite | \~70% | Its critic blocks hallucinated columns, PII columns, uncertified tables and non-read-only SQL. It does not check that a query applies a business definition. |
| [sql-analyst-agent](https://github.com/olsongl/sql-agent) | Multi-agent analyst that plans, writes, validates, executes and explains SQL | \~50% | Validation is sqlglot plus EXPLAIN. No business-rule layer, no rule-compliance result. |
| [Wren AI](https://github.com/Ray0907/WrenAI) | Open-source generative BI with a version-controlled semantic layer (MDL) | \~45% | Definitions guide SQL generation up front. There is no separate post-generation audit. It is a full platform, far larger than this MVP. |
| [Vanna](https://www.sourcepulse.org/projects/1595837) | Retrieval over schema, docs and example SQL to prompt the LLM | \~30% | Retrieval only. No deterministic rule check or audit trail. |
| [Dataherald](https://cdn.jsdelivr.net/gh/dataherald/dataherald@main/README.md) | Enterprise natural-language-to-SQL engine with API, admin console and Slackbot | \~30% | Product-scale engine built on LLM agents and golden SQL examples. No rule audit. |
| [sql-guardrail](https://pypi.org/project/sql-guardrail/0.5.2/), [ProxQL](https://pypi.org/project/proxql/), [NL2BI](https://pypi.org/project/nl2bi/) | SQL safety validation for LLM output | \~25% (guardrail module only) | Safety only. None check business-rule correctness. |

**The difference to own.** Business definitions are stored as data with explicit `required_filters`. A deterministic checker tests the parsed SQL against the rules retrieved for that question and returns pass or fail with the rule IDs and reasons. Every answer cites the rule versions it was checked against.

**Not different, so do not claim as novel.** A multi-agent pipeline, SQLite with sqlglot guardrails, read-only execution, and a baseline comparison all exist already.

**Positioning.** Describe the project as a rule-compliance auditor for text-to-SQL, name Datum as related work in the README, and write the code independently.

## Goals, scope and non-goals

The MVP answers one question well: does this generated query follow the company's own rules?

**Goals**

- Accept natural-language questions about one known SQLite database of synthetic data.
- Retrieve the relevant schema entries and business rules for each question.
- Generate SQL, then validate it for safety and for rule compliance before execution.
- Run only approved, read-only queries with row and time limits.
- Return the answer with the executed SQL, the rule IDs and versions used, and each check's outcome.
- Keep an audit record per request, and compare the system with two simpler baselines on a fixed test set.

**Non-goals for the first version**

- Other databases or SQL dialects, a polished front end, or real company data.
- Any write operation: INSERT, UPDATE, DELETE, DDL or stored procedures.
- Discovering rules automatically from arbitrary documents.
- Guaranteeing that generated SQL is correct, or replacing database permissions and human review.
- Calling the design multi-agent unless the evaluation shows separate agents help.

## Rule format and semantic audit design

Each business rule is a version-controlled file with a stable ID and machine-readable checks. The auditor reads those checks and tests the parsed SQL against them, so a new rule means a new file, not new code.

The example below is illustrative. Inspect the OKF repository first and adapt the format to its real conventions before adopting it.

```yaml
id: metric.departmental_spend
version: 1
title: Departmental spend
definition: Sum of approved expenses inside the fiscal year.
required_filters:
  - column: expenses.status
    operator: "="
    value: "approved"
  - column: expenses.expense_date
    type: fiscal_year_range
```

**How the check runs**

1. Parse the candidate SQL with SQLGlot into a syntax tree.
2. Collect the conditions in WHERE clauses and JOIN ... ON, resolving table aliases to real table names.
3. Normalize equivalent forms, so `status = 'approved'` and `status IN ('approved')` match.
4. For each required filter in each retrieved rule, test that a matching condition exists. For a range filter, check that both bounds match the fiscal-year definition.
5. Return pass, or fail with the rule ID and a reason such as "missing required filter: expenses.status = 'approved'".
6. On a fail, allow one revision with the reason fed back to the generator, then reject. Never execute a failed query.

**Initial rule types**

- `required_filter`: a condition that must appear.
- `required_join`: a relationship that must be used.
- `forbidden_substitute`: a similarly named column that must not stand in for the defined concept, such as `is_active` for an active customer.

**Limits to state openly**

- Only rules that can be written as explicit conditions are enforced. Subtle logic errors can slip through.
- CTEs, subqueries and aliases make condition matching harder. Start with single-level queries and simple joins, and say what is unsupported.
- An LLM reviewer may add a second opinion. It is recorded as a signal and never overrides a failed deterministic check.

## Guardrails and security

Safety is enforced by ordinary code in layers, and no model output can override it. If any check cannot establish that a query is allowed, the system does not execute it.

1. **Parse.** SQLGlot must understand the statement. Anything it cannot classify is rejected.
2. **Statement policy.** One statement only, and it must be a SELECT. No DDL, DML, administrative commands or multiple statements. A keyword denylist alone is not enough, because of comments, nested queries and dialect syntax.
3. **Allowlists.** Only approved tables and columns. Unknown identifiers are rejected, which also catches invented schema names.
4. **Read-only connection.** SQLite opened with `mode=ro`, so a write fails at the database even if a check is bypassed.
5. **Resource limits.** Row cap and a wall-clock timeout.
6. **Audit.** Every rejection is logged with its reason and without secrets.

| Threat | Mitigation |
| --- | --- |
| Destructive generated SQL | Parsed SELECT-only policy plus a read-only connection |
| Unauthorized table or column | Allowlists and least-privilege access |
| Expensive query | Row cap, timeout, small controlled dataset |
| Invented table or column | Check every identifier against the live schema |
| Prompt injection in a knowledge file or question | Treat retrieved text as data, never as instructions |
| Wrong or outdated rule | Versioned rules, tests, and the version cited in each answer |
| Sensitive data in logs | Redaction rules and retention defined before real data is used |
| Model unavailable | Return a controlled error and never skip validation |

**Out of scope for the MVP.** A read-only query can still reveal too much to a user who has too much access. Authentication, authorization, monitoring and a security review would be required before any production use.

## Evaluation plan

The evaluation decides whether this project is a portfolio piece or a demo. The key experiment targets the gap in Related work: queries that are valid and safe but violate a business rule.

**Test set.** Write 50 to 100 synthetic questions, each with a hand-verified gold SQL or expected result. Cover:

- Plain filters, aggregations and joins.
- Metrics with explicit definitions and fiscal-year boundaries.
- Valid queries that violate a rule. This is the key category, and these cases should be written before the rules are finalized.
- Ambiguous requests that need clarification.
- Unknown tables or columns, and prohibited operations.
- Prompt-injection attempts in a question or a knowledge file.
- Empty results and database errors.

**Configurations compared**

1. Baseline A: question and schema only.
2. Baseline B: question, schema and retrieved rules, with no audit.
3. Proposed: retrieval, deterministic guardrails and the rule-compliance audit.
4. Optional ablation: the audit with and without an LLM reviewer, and a rule-based router with and without Jev.

| Metric | What it measures |
| --- | --- |
| Execution accuracy | Result matches the expected result on the test database |
| Business-rule compliance | Query applies every required rule |
| Unsafe-query rejection rate | Share of disallowed queries rejected |
| False rejection rate | Share of valid queries wrongly rejected |
| Evidence accuracy | Cited rule IDs actually support the answer |
| Latency | End-to-end response time |

**Avoid circular evaluation.** If the same person writes the rules and the tests, the auditor can look better than it is. Add rule-violating cases phrased differently from the rules, and report failures and false rejections alongside successes.

Report the real number of test cases and real results. Do not state target scores as achievements.
