# Enterprise Multi-Agent SQL & Knowledge Auditor

## Detailed Project Design and Implementation Report

**Working name:** Enterprise SQL Auditor\
**Project type:** AI engineering, natural-language-to-SQL, knowledge
retrieval, database safety, and auditability\
**Status:** Proposed design --- implementation and evaluation results
are not yet available\
**Target:** A no-cost, local-first MVP suitable for a student portfolio

------------------------------------------------------------------------

## 1. Executive Summary

Enterprise Multi-Agent SQL & Knowledge Auditor is a local-first system
that converts natural-language business questions into SQL, checks the
generated query against database structure and company-specific business
rules, executes only queries that pass deterministic safety checks, and
returns an answer with an audit trail.

The project addresses a real weakness in basic text-to-SQL systems: a
query can be syntactically valid and execute successfully while still
answering the wrong business question. For example, a database may
contain an `is_active` field, but a company may define an "active
customer" as someone who made a purchase within the last 90 days. A
model that uses the field without consulting the business definition can
return a plausible but incorrect result.

The proposed system combines:

-   **Structured knowledge files:** Store business definitions,
    policies, schema descriptions, and metric rules in an OKF-compatible
    format, after confirming the exact format and capabilities of the
    selected repository.
-   **Routing and retrieval:** Select relevant business knowledge,
    schema details, and workflow based on the user's question. Jev may
    be used if its actual API and behavior fit this role.
-   **SQL generation:** Generate a query using the question, relevant
    schema, and retrieved rules.
-   **Deterministic guardrails:** Parse and validate SQL, enforce
    read-only execution, restrict tables and columns, and apply resource
    limits.
-   **Independent review:** Check the proposed query against the
    business intent and rules. An LLM review can supplement but never
    replace deterministic checks.
-   **Auditing and evaluation:** Keep traceable records of the question,
    selected knowledge, SQL, validation decisions, execution outcome,
    and answer.

The project's central hypothesis is that combining business-rule-aware
retrieval with deterministic SQL guardrails can reduce semantic errors
and unsafe queries compared with a basic text-to-SQL baseline. This is a
hypothesis to test, not a result to claim in advance.

------------------------------------------------------------------------

## 2. Problem Statement

Organizations often store data in relational databases but express
business questions in natural language. Translating these questions into
SQL requires more than knowing SQL syntax. A reliable system needs to
understand:

1.  The database schema and relationships.
2.  Business definitions that may not be obvious from column names.
3.  Company policies and metric calculation rules.
4.  Which operations a user is permitted to perform.
5.  Whether the generated query actually answers the requested question.
6.  How to explain and audit the final result.

A generic model may invent table or column names, join tables
incorrectly, apply the wrong date range, misunderstand a business
metric, or generate expensive or unauthorized queries. A successful
execution does not prove that a query is semantically correct.

### Example failure

Suppose the database has these fields:

-   `customers.is_active`
-   `orders.customer_id`
-   `orders.order_date`

The company defines an active customer as one with at least one
completed purchase during the last 90 days. A model that filters only on
`customers.is_active = TRUE` may produce a valid SQL query that violates
the company's definition.

The proposed auditor should retrieve the formal definition, check the
query's logic against it, and either correct the query or flag the
mismatch.

------------------------------------------------------------------------

## 3. Goals and Non-Goals

### Goals

-   Accept natural-language questions about a known relational database.
-   Retrieve the relevant schema descriptions and business definitions.
-   Generate SQL grounded in the available schema.
-   Validate SQL before execution.
-   Enforce read-only access and query constraints.
-   Check selected business rules and metric definitions.
-   Return results with source references and validation explanations.
-   Record an audit trail for debugging and evaluation.
-   Compare the system with simpler baselines using a repeatable test
    set.
-   Run locally with free and open-source components wherever practical.

### Non-goals for the first version

-   Supporting every SQL dialect or every database engine.
-   Automatically discovering every company policy from arbitrary
    documents.
-   Guaranteeing that an LLM-generated query is correct.
-   Replacing database permissions, governance systems, or human
    approval.
-   Executing unrestricted `INSERT`, `UPDATE`, `DELETE`, DDL, stored
    procedures, or administrative statements.
-   Claiming that OKF or Jev eliminates the need for retrieval or that
    this system replaces all RAG architectures.
-   Deploying to production with sensitive enterprise data.

------------------------------------------------------------------------

## 4. Target Users and Use Cases

### Target users

-   Data analysts who need help translating business questions into SQL.
-   Data and analytics engineering teams that maintain shared metric
    definitions.
-   Internal audit or governance teams that need query traceability.
-   Developers prototyping policy-aware database assistants.

### Initial use cases

1.  Ask for departmental spending compared with approved budgets.
2.  Identify customers meeting a company-defined activity rule.
3.  Compare expense claims with reimbursement policy.
4.  Find departments whose spending exceeded a threshold.
5.  Explain which tables, joins, filters, and business definitions were
    used.
6.  Reject a request that requires a prohibited operation or
    unauthorized table.

The MVP should use synthetic data only.

------------------------------------------------------------------------

## 5. Proposed System Architecture

``` text
                    ┌───────────────────────┐
                    │ User's natural-language│
                    │ business question      │
                    └───────────┬───────────┘
                                │
                                v
                    ┌───────────────────────┐
                    │ API and request checks │
                    └───────────┬───────────┘
                                │
                                v
                    ┌───────────────────────┐
                    │ Intent / workflow      │
                    │ router                 │
                    └───────────┬───────────┘
                                │
                 ┌──────────────┴──────────────┐
                 v                             v
       ┌────────────────────┐       ┌────────────────────┐
       │ Schema and metadata│       │ OKF-compatible     │
       │ retrieval          │       │ business knowledge │
       └──────────┬─────────┘       └──────────┬─────────┘
                  └──────────────┬─────────────┘
                                 v
                    ┌───────────────────────┐
                    │ SQL planner / generator│
                    └───────────┬───────────┘
                                │
                                v
                    ┌───────────────────────┐
                    │ Deterministic SQL      │
                    │ guardrails             │
                    └───────────┬───────────┘
                                │
                                v
                    ┌───────────────────────┐
                    │ Semantic/business-rule│
                    │ review                │
                    └───────────┬───────────┘
                                │
                       pass / reject / revise
                                │
                                v
                    ┌───────────────────────┐
                    │ Read-only execution   │
                    │ against test database │
                    └───────────┬───────────┘
                                │
                                v
                    ┌───────────────────────┐
                    │ Answer + evidence +   │
                    │ audit record          │
                    └───────────────────────┘
```

### Architecture principles

-   **Deterministic checks are authoritative for safety.** The model
    cannot override a failed safety check.
-   **Retrieval is explicit.** The system should be able to show which
    schema entries and business rules informed the query.
-   **No hidden execution.** The UI or API should distinguish generated
    SQL from executed SQL.
-   **Fail closed.** If the SQL parser, permissions check, or policy
    validator cannot establish that a query is allowed, do not execute
    it.
-   **Keep the first version simple.** A modular pipeline is sufficient;
    multiple autonomous agents are not required just to call the system
    "multi-agent."

------------------------------------------------------------------------

## 6. Components and Responsibilities

### 6.1 API layer

Responsibilities:

-   Accept the user's question and optional dataset selection.
-   Validate request length and required fields.
-   Assign a request identifier.
-   Return structured results and clear errors.
-   Avoid exposing secrets, credentials, or internal stack traces.

Suggested implementation: FastAPI with Pydantic request and response
models.

### 6.2 Schema inspector

Responsibilities:

-   Read table and column names, data types, primary keys, and foreign
    keys from the test database.
-   Create a compact schema representation for retrieval and SQL
    generation.
-   Optionally include curated table and column descriptions.
-   Detect when generated SQL refers to unknown identifiers.

For the MVP, use SQLite. A later version can add PostgreSQL.

### 6.3 Knowledge store using OKF-compatible files

Store business knowledge as version-controlled files, for example:

``` text
knowledge/
  policies/
    expense_reimbursement.md
    customer_activity.md
  metrics/
    departmental_spend.md
  schema/
    customers.md
    orders.md
    expenses.md
  relationships/
    customer_orders.md
```

A possible illustrative file:

``` yaml
---
id: metric.active_customer
type: business_definition
title: Active customer
version: 1
---

## Definition

A customer is considered active if they have at least one completed
purchase in the rolling 90-day period.

## Data mapping

- Customer table: customers
- Orders table: orders
- Date field: orders.order_date
- Completion field: orders.status

## Rule

Count distinct customers with at least one order whose status is
`completed` and whose order date falls within the defined 90-day window.
```

This is an illustrative Markdown-with-front-matter structure, not a
claim that it exactly matches the repository's OKF schema. Before
implementation, inspect the referenced repository and adapt the file
format to its actual conventions.

Requirements:

-   Stable IDs for policies and metrics.
-   Versioning and change history.
-   Explicit data mappings.
-   Clear definitions and exceptions.
-   Source references in the final answer.
-   Tests that check policy files can be loaded and parsed.

### 6.4 Router and retrieval

The router decides what the question requires. For example:

-   A question about a business metric needs metric definitions and
    schema details.
-   A question about reimbursement needs policy rules and expense
    tables.
-   An ambiguous question may require clarification.
-   A prohibited or unsupported request should be rejected before SQL
    execution.

Start with a simple, testable router. Use keyword/rule-based routing as
a baseline and compare it with any Jev-based implementation. Confirm
Jev's real API, license, supported inputs, and behavior from its source
documentation before integrating it. Do not assume that it provides
semantic routing, retrieval, or policy enforcement unless verified.

Retrieval can begin with exact metadata filters and BM25-style lexical
search. Embeddings are optional, not mandatory for the MVP.

### 6.5 SQL planner and generator

Inputs:

-   User question.
-   Relevant schema.
-   Retrieved business definitions and policies.
-   SQL dialect and execution constraints.

Outputs:

-   Candidate SQL.
-   A short explanation of the intended logic.
-   Referenced knowledge IDs.
-   Any assumptions or ambiguities.

The generator must not be allowed to execute SQL directly. SQL
generation and SQL execution should be separate modules.

### 6.6 Deterministic SQL guardrails

At minimum:

-   Parse SQL using a dialect-aware SQL parser.
-   Allow only a single read-only `SELECT` query in the MVP.
-   Reject multiple statements.
-   Reject DDL, DML, administrative commands, and disallowed functions.
-   Enforce table and column allowlists.
-   Enforce a maximum row count.
-   Set a query timeout where supported.
-   Use a database account with read-only permissions where supported.
-   Use a disposable synthetic database during development.
-   Log the reason for rejection without logging secrets.

A keyword denylist alone is not sufficient: SQL can contain comments,
nested queries, dialect-specific syntax, and alternate spellings. Use
parsing plus database-level controls. A read-only connection is an
additional protection, not a replacement for validation.

### 6.7 Semantic and policy auditor

This component checks whether the candidate query reflects the question
and relevant business rules.

Possible checks:

-   Required filters are present.
-   The expected join relationships are used.
-   The correct metric definition is applied.
-   Date boundaries and status conditions are consistent with policy.
-   The requested output columns match the intent.
-   The SQL does not silently substitute a similarly named field for the
    defined business concept.

Use deterministic checks for rules that can be represented explicitly.
An LLM reviewer may flag subtle mismatches, but its decision should be
recorded as a review signal, not treated as proof of correctness.

If a check fails, the system should either request a revision, ask the
user to clarify the question, or refuse execution.

### 6.8 Read-only executor

Responsibilities:

-   Execute only approved SQL.
-   Apply time and result-size limits.
-   Return typed rows and column metadata.
-   Handle errors without exposing internal secrets.
-   Avoid executing a query again unless a deliberate retry policy
    permits it.

For SQLite, create a controlled test database and use the engine's
read-only mode where practical. For PostgreSQL, create a dedicated role
with only the required `SELECT` privileges and enforce server-side
limits.

### 6.9 Answer and evidence builder

The final response should contain:

-   A concise answer based on the returned rows.
-   The executed SQL.
-   The business definitions and policy IDs used.
-   The tables and columns referenced.
-   Guardrail and semantic-review outcomes.
-   Warnings or limitations, where relevant.

The answer must not imply that a policy was checked if it was not
retrieved or validated.

### 6.10 Audit log

Record, with appropriate redaction:

-   Request ID and timestamp.
-   User question or a privacy-safe representation.
-   Retrieved knowledge IDs and versions.
-   Candidate SQL and final executed SQL.
-   Guardrail outcomes and rejection reasons.
-   Execution status and row count.
-   Final response status.
-   Model and configuration identifiers, where relevant.

For the local MVP, a JSON Lines file or a dedicated SQLite audit table
is sufficient. Define retention and redaction rules before using real
data.

------------------------------------------------------------------------

## 7. Multi-Agent Design: Use Roles Only Where They Add Value

The title includes "Multi-Agent," but the project should not use agents
merely to make the architecture look advanced.

A practical design has three logical roles:

1.  **Planner:** Interprets the question, identifies needed schema and
    knowledge, and produces a query plan.
2.  **SQL generator:** Converts the plan into candidate SQL.
3.  **Auditor:** Independently reviews the candidate against the user's
    intent and retrieved rules.

The deterministic guardrail and executor remain ordinary software
components, not LLM agents.

For the first milestone, implement these as separate Python modules with
typed inputs and outputs. This provides testability without requiring an
agent framework. Add independent LLM calls only if experiments show
measurable improvement over a single-model pipeline.

Do not allow the auditor agent to approve a query that the deterministic
guardrail rejected.

------------------------------------------------------------------------

## 8. Example End-to-End Scenario

### Synthetic database

-   `departments(id, name)`
-   `budgets(department_id, fiscal_year, approved_amount)`
-   `expenses(id, department_id, amount, status, expense_date)`

### Business rule

Only approved expenses count toward actual departmental spend. Spending
is considered over budget when approved spend exceeds the approved
budget for the same department and fiscal year.

### User question

"Which departments exceeded their approved travel budget this fiscal
year?"

### Expected system behavior

1.  The router identifies a departmental budget comparison.
2.  Retrieval returns the relevant spending metric definition, expense
    policy, fiscal-year rule, and table relationships.
3.  The planner identifies the required grouping, status filter, and
    budget join.
4.  The SQL generator produces a candidate query.
5.  The deterministic validator checks that only allowed tables are used
    and that the statement is read-only.
6.  The semantic auditor checks that the approved-expense filter and
    fiscal-year boundaries match the retrieved definitions.
7.  The query executes against the synthetic database.
8.  The response reports matching departments and amounts, cites the
    knowledge IDs, and exposes the executed SQL.

If the query includes all expenses regardless of status, the system
should flag the missing filter. It should not simply return the result
because the SQL executes successfully.

------------------------------------------------------------------------

## 9. Suggested Technology Stack

  -----------------------------------------------------------------------
  Layer                   Suggested technology    Reason
  ----------------------- ----------------------- -----------------------
  Language                Python                  Ecosystem for APIs,
                                                  SQL, parsing, and AI
                                                  integration

  API                     FastAPI                 Typed HTTP endpoints
                                                  and API documentation

  Request/response        Pydantic                Explicit data contracts
  validation                                      

  Initial database        SQLite                  Local, simple, no
                                                  separate server
                                                  required

  Later database option   PostgreSQL              More realistic roles
                                                  and permission controls

  SQL validation          SQLGlot or another      Parse and inspect SQL
                          dialect-aware parser    structurally

  Knowledge files         Markdown plus           Version-controlled
                          YAML/front matter,      business rules
                          adapted to the actual   
                          OKF repository          

  Search baseline         Metadata filtering and  Easy to measure and
                          BM25/lexical search     debug

  Local model             Ollama-compatible local Avoid paid inference
                          model, if hardware      APIs
                          supports it             

  Tests                   pytest                  Unit, integration,
                                                  regression, and safety
                                                  tests

  Front end               Optional React          Useful after the
                          interface               backend works

  Audit trail             JSONL or SQLite table   Easy local inspection
  -----------------------------------------------------------------------

### Cost and feasibility

The MVP can be built without paid cloud services. A local model is
optional and may be slow or resource-intensive on modest hardware. Begin
with a mock model or a locally available model to develop the pipeline,
then benchmark the selected model. Do not make a paid API a hard
dependency.

Check each dependency's current license, installation requirements, API
stability, and local resource needs before selecting it for the final
repository.

------------------------------------------------------------------------

## 10. Repository Layout

``` text
enterprise-sql-auditor/
├── README.md
├── pyproject.toml
├── .env.example
├── knowledge/
│   ├── policies/
│   ├── metrics/
│   ├── schema/
│   └── relationships/
├── data/
│   └── seed_synthetic_data.py
├── src/
│   └── sql_auditor/
│       ├── api.py
│       ├── config.py
│       ├── schema_inspector.py
│       ├── knowledge_loader.py
│       ├── retrieval.py
│       ├── router.py
│       ├── planner.py
│       ├── sql_generator.py
│       ├── sql_guardrails.py
│       ├── semantic_auditor.py
│       ├── executor.py
│       ├── answer_builder.py
│       └── audit_log.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── safety/
│   └── evaluation/
└── docs/
    ├── architecture.md
    ├── threat_model.md
    └── evaluation.md
```

Keep the system modular. Do not put retrieval, generation, execution,
and validation into one large function.

------------------------------------------------------------------------

## 11. API Design

Potential endpoints:

### `POST /ask`

Example request:

``` json
{
  "question": "Which departments exceeded their approved budget this fiscal year?"
}
```

Illustrative response:

``` json
{
  "request_id": "example-request-id",
  "status": "executed",
  "answer": "Department A exceeded its approved budget by ...",
  "sql": "SELECT ...",
  "knowledge_sources": [
    "metric.departmental_spend",
    "policy.fiscal_year"
  ],
  "checks": {
    "read_only": "passed",
    "schema_validation": "passed",
    "policy_review": "passed"
  },
  "row_count": 1
}
```

The example response is a proposed schema, not a real execution result.
Amounts and query results should come from the test database, not
hardcoded examples.

### Other useful endpoints

-   `GET /health` --- service health.
-   `GET /schema` --- available schema metadata, with no secrets.
-   `GET /audit/{request_id}` --- retrieve the audit record subject to
    access controls.

For an MVP, one `/ask` endpoint and a health endpoint are enough.

------------------------------------------------------------------------

## 12. Security and Threat Model

The system processes model-generated SQL, so safety must be designed
into the execution path.

### Threats and mitigations

  -----------------------------------------------------------------------
  Threat                              Mitigation
  ----------------------------------- -----------------------------------
  Generated destructive SQL           Allow only parsed, approved
                                      read-only queries; use read-only
                                      database permissions

  Unauthorized table access           Table/column allowlists and
                                      least-privilege database
                                      credentials

  Expensive query                     Row limits, timeouts, query-plan
                                      checks where feasible, controlled
                                      dataset

  Prompt injection in knowledge       Treat retrieved content as data,
  documents                           not instructions; separate policy
                                      data from system control

  Fabricated schema references        Inspect the live test schema and
                                      reject unknown identifiers

  Incorrect business definition       Versioned definitions, explicit
                                      mappings, tests, and semantic
                                      checks

  Misleading explanation              Ground the explanation in executed
                                      results and retrieved sources

  Sensitive information in logs       Redact credentials and sensitive
                                      values; define retention

  Model unavailable                   Return a controlled error; never
                                      bypass validation to keep the
                                      system running

  Reviewer disagreement               Fail closed or request
                                      clarification; do not let an LLM
                                      override deterministic rejection
  -----------------------------------------------------------------------

### Important limitations

-   A read-only query can still expose sensitive information if the
    caller is authorized to see too much.
-   SQL parsing alone does not guarantee semantic correctness.
-   A model-based auditor can make mistakes.
-   Policies can be incomplete, contradictory, or out of date.
-   Production use would require authentication, authorization,
    monitoring, data governance, and security review beyond the student
    MVP.

------------------------------------------------------------------------

## 13. Evaluation Plan

Evaluation is a core part of the project. A demo with a few handpicked
successful questions is not enough.

### Build a test set

Create at least 50--100 synthetic questions with expected outcomes,
covering:

-   Straightforward filters and aggregations.
-   Joins across known relationships.
-   Business metrics with explicit definitions.
-   Date boundaries and fiscal-year logic.
-   Ambiguous requests that should trigger clarification.
-   Unknown tables or columns.
-   Prohibited operations.
-   Queries that execute but violate a business rule.
-   Prompt-injection attempts in a knowledge file or user question.
-   Empty results and database errors.

Use a manually verified gold SQL query or expected result for each
supported test case. Document ambiguous cases rather than treating one
interpretation as the only correct answer.

### Baselines

Compare at least these configurations:

1.  **Baseline A --- Basic text-to-SQL:** Question and schema only.
2.  **Baseline B --- Retrieval-augmented text-to-SQL:** Question,
    schema, and retrieved business knowledge.
3.  **Proposed system --- Retrieval + routing + deterministic
    guardrails + semantic audit.**

If Jev is integrated, add an ablation that compares the router with and
without Jev. This tests whether it contributes measurable value.

### Metrics

  -----------------------------------------------------------------------
  Metric                              What it measures
  ----------------------------------- -----------------------------------
  Execution accuracy                  Whether query results match the
                                      expected result on the test
                                      database

  Exact SQL match                     Whether generated SQL matches the
                                      gold query; useful but too strict
                                      as a sole metric

  Business-rule compliance            Whether the query applies required
                                      definitions and policy filters

  Unsafe-query rejection rate         Proportion of disallowed test
                                      queries rejected

  False rejection rate                Proportion of valid supported
                                      queries incorrectly rejected

  Evidence accuracy                   Whether cited knowledge IDs
                                      actually support the explanation

  Clarification quality               Whether ambiguous questions trigger
                                      useful clarification

  Latency                             End-to-end response time

  Token/resource use                  Model tokens, memory, or local
                                      inference cost where measurable
  -----------------------------------------------------------------------

Report the number of test cases and actual results. Do not invent target
scores and present them as achievements. Compare error categories as
well as aggregate metrics.

------------------------------------------------------------------------

## 14. Development Roadmap

### Phase 1 --- Define the problem and data

-   Select SQLite and create a synthetic business dataset.
-   Define table relationships and 8--15 business rules.
-   Create manually verified example questions and expected SQL/results.
-   Document supported question types and limitations.

**Exit criterion:** The schema, policies, and test cases are explicit
and reproducible.

### Phase 2 --- Build a deterministic baseline

-   Implement schema inspection.
-   Build a basic SQL-generation interface with a mock response
    initially.
-   Implement SQL parsing and safety checks.
-   Execute approved read-only queries.
-   Add unit tests for prohibited statements.

**Exit criterion:** The system can safely execute approved test queries
and reject disallowed SQL.

### Phase 3 --- Add knowledge retrieval

-   Create OKF-compatible knowledge files using the repository's actual
    conventions.
-   Implement a knowledge loader and retrieval baseline.
-   Pass retrieved definitions and schema context to the generator.
-   Return knowledge source IDs with each answer.

**Exit criterion:** Questions retrieve the intended business
definitions, and the answer identifies the sources used.

### Phase 4 --- Add routing and auditing

-   Implement routing for metric questions, policy questions,
    unsupported requests, and ambiguous questions.
-   Integrate Jev only after verifying its interface and expected
    behavior.
-   Add semantic review for defined business rules.
-   Add controlled revise-or-reject behavior.

**Exit criterion:** Known semantic mistakes are detected in a regression
test set.

### Phase 5 --- Evaluate and compare

-   Run the same test set against the baselines and proposed system.
-   Categorize errors.
-   Measure accuracy, policy compliance, false rejections, and latency.
-   Remove components that add complexity without measurable benefit.

**Exit criterion:** A reproducible evaluation report describes actual
results and limitations.

### Phase 6 --- Polish for a portfolio

-   Add a simple interface only after the backend and tests are
    reliable.
-   Add architecture and threat-model documentation.
-   Include setup steps and sample synthetic data.
-   Record a short demo showing a valid query, a semantic mismatch, and
    a rejected unsafe query.

**Exit criterion:** A reviewer can run the project locally and reproduce
the demonstration.

------------------------------------------------------------------------

## 15. Acceptance Criteria for the MVP

The MVP is ready for a portfolio demo when:

-   [ ] It runs locally without requiring a paid cloud account.
-   [ ] It uses a documented synthetic database.
-   [ ] Knowledge files have stable IDs and are version controlled.
-   [ ] The system retrieves the relevant business rule for supported
    test questions.
-   [ ] It produces SQL grounded in the inspected schema.
-   [ ] It rejects destructive and multi-statement SQL.
-   [ ] It applies table allowlists and query/result limits.
-   [ ] It uses read-only database access where supported.
-   [ ] It detects at least several deliberately constructed
    semantic-rule violations.
-   [ ] It asks for clarification when a question is materially
    ambiguous.
-   [ ] It returns source IDs and an audit record.
-   [ ] Automated tests cover success, failure, and adversarial cases.
-   [ ] Baseline comparisons and actual measured results are documented.
-   [ ] The README clearly lists limitations and does not claim
    unmeasured accuracy.

------------------------------------------------------------------------

## 16. Main Risks and Mitigations

### Risk: Too much scope

Trying to build a general multi-agent platform, support multiple
databases, and create a polished frontend at once will delay the core
value.

**Mitigation:** Start with SQLite, a single synthetic domain, a single
API endpoint, and a small set of explicit rules.

### Risk: Multi-agent complexity without gains

Several LLM calls can increase latency and create disagreement without
improving correctness.

**Mitigation:** Implement a modular single-pipeline baseline first. Add
separate agent calls only when an ablation demonstrates improvement.

### Risk: OKF or Jev integration assumptions are wrong

The project's name alone does not establish the exact schema, APIs,
licensing, or capabilities of the referenced repository.

**Mitigation:** Inspect the source, README, license, dependencies,
examples, and tests before committing to integration. Keep the knowledge
layer and router behind small interfaces so they can be replaced.

### Risk: Weak evaluation

A small demo may hide incorrect SQL and false rejections.

**Mitigation:** Create a fixed, versioned test set with gold results and
adversarial cases. Report both successes and failures.

### Risk: The project is perceived as a generic SQL chatbot

Natural-language-to-SQL is an established area.

**Mitigation:** Center the project on semantic business-rule auditing,
deterministic safety controls, evidence provenance, and measured
comparisons rather than the chat interface.

------------------------------------------------------------------------

## 17. What Is Actually Novel Here?

The individual technologies are not inherently novel. Text-to-SQL,
retrieval, SQL parsing, policy rules, and agent workflows already exist.

The defensible project contribution is an integrated and evaluated
workflow that:

1.  Represents business definitions as versioned, traceable knowledge.
2.  Retrieves those definitions for natural-language database questions.
3.  checks generated SQL against both database structure and explicit
    business rules.
4.  Enforces query safety independently of the model.
5.  records evidence and validation decisions.
6.  quantitatively compares this design with simpler baselines.

Do not describe it as a universal replacement for RAG. The better claim
is that it explores a structured, auditable approach to
knowledge-grounded SQL generation and evaluates when that approach is
useful.

------------------------------------------------------------------------

## 18. Recommended Build Order

The safest and most informative sequence is:

1.  **Create the SQLite dataset and manually verified test cases.**
2.  **Build deterministic SQL validation and read-only execution.**
3.  **Add a basic text-to-SQL baseline.**
4.  **Add structured business knowledge and retrieval.**
5.  **Add policy-aware semantic checks and evidence reporting.**
6.  **Test Jev as an optional router and measure its impact.**
7.  **Add a multi-agent workflow only if the evaluation supports it.**
8.  **Add a UI and prepare the portfolio demo.**

This order reduces the chance of spending time on agent orchestration
before establishing that the underlying SQL and policy checks work.

------------------------------------------------------------------------

## 19. Final Recommendation

Proceed with the project, but use the following definition:

> **Enterprise Multi-Agent SQL & Knowledge Auditor is a local-first,
> policy-aware text-to-SQL system that grounds queries in structured
> business knowledge, validates SQL with deterministic safety controls,
> checks business-rule consistency, and provides evidence-backed answers
> with an auditable execution trail.**

The strongest demonstration is not a successful SQL answer alone. Show
three cases:

1.  A valid business question answered correctly.
2.  A syntactically valid query that violates a company-defined metric
    and is caught by the auditor.
3.  An unsafe or unsupported request that is rejected without execution.

These cases demonstrate the project's actual engineering contribution.
Keep all performance claims tied to measured test results, and verify
the exact OKF and Jev interfaces before describing them as implemented
capabilities.
