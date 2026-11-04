"""
Unit tests for SQL Generator and Model Backends (sql_generator.py).
"""

import pytest
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend, OllamaBackend


@pytest.fixture(scope="module")
def schema():
    return inspect_schema()


@pytest.fixture(scope="module")
def bundle(schema):
    return load_knowledge_bundle(schema=schema)


def test_build_prompt_contains_schema_and_rules(schema, bundle):
    backend = MockGeneratorBackend()
    generator = SQLGenerator(backend=backend, schema=schema)

    rules = [bundle.get("metric.departmental_spend")]
    prompt = generator.build_prompt(
        question="What was spend in 2024?",
        rules=rules,
        revision_feedback=None,
    )
    assert "DATABASE SCHEMA" in prompt
    assert "departments" in prompt
    assert "expenses" in prompt
    assert "MANDATORY BUSINESS RULES" in prompt
    assert "metric.departmental_spend" in prompt
    assert "expenses.status = 'approved'" in prompt


def test_build_prompt_includes_revision_feedback(schema, bundle):
    backend = MockGeneratorBackend()
    generator = SQLGenerator(backend=backend, schema=schema)

    rules = [bundle.get("metric.departmental_spend")]
    prompt = generator.build_prompt(
        question="What was spend in 2024?",
        rules=rules,
        revision_feedback="Missing required filter: expenses.status = 'approved'.",
    )
    assert "PREVIOUS ATTEMPT FAILED COMPLIANCE AUDIT" in prompt
    assert "Missing required filter: expenses.status = 'approved'." in prompt


def test_extract_sql_from_markdown():
    markdown_output = """
Here is the query:
```sql
SELECT id, name FROM departments;
```
Hope that helps!
    """
    extracted = SQLGenerator.extract_sql(markdown_output)
    assert extracted == "SELECT id, name FROM departments;"


def test_mock_generator_keyword_matching(schema, bundle):
    backend = MockGeneratorBackend(
        responses={"spend": "SELECT d.name, sum(e.amount) FROM departments d JOIN expenses e ON d.id=e.department_id GROUP BY d.name;"}
    )
    generator = SQLGenerator(backend=backend, schema=schema)

    res = generator.generate_candidate_sql(
        question="What was departmental spend?",
        rules=[bundle.get("metric.departmental_spend")],
    )
    assert "departments" in res.sql
    assert "expenses" in res.sql
    assert res.attempt == 1


def test_mock_generator_revision_switch(schema, bundle):
    backend = MockGeneratorBackend(
        responses={
            "spend": "SELECT sum(amount) FROM expenses;",
            "revised:missing required filter": "SELECT sum(amount) FROM expenses WHERE status = 'approved';",
        }
    )
    generator = SQLGenerator(backend=backend, schema=schema)

    # First attempt: without revision feedback
    res1 = generator.generate_candidate_sql(
        question="What was total spend?",
        rules=[bundle.get("metric.departmental_spend")],
        revision_feedback=None,
    )
    assert "WHERE status = 'approved'" not in res1.sql

    # Second attempt: with revision feedback
    res2 = generator.generate_candidate_sql(
        question="What was total spend?",
        rules=[bundle.get("metric.departmental_spend")],
        revision_feedback="Missing required filter: status = 'approved'",
        attempt=2,
    )
    assert "WHERE status = 'approved'" in res2.sql
    assert res2.attempt == 2

