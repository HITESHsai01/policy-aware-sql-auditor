"""
Integration tests for the Revise-or-Reject Control Loop (pipeline.py).
"""

import pytest
from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.executor import SafeExecutor
from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
from sql_auditor.pipeline import AuditorPipeline, IntentType


@pytest.fixture(scope="module")
def setup_pipeline():
    schema = inspect_schema()
    bundle = load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)
    executor = SafeExecutor(db_path=DEFAULT_DB_PATH)
    return schema, bundle, executor


def test_revision_loop_fixes_missing_filter(setup_pipeline):
    """
    Scenario 1: Initial query omits 'expenses.status = approved'.
    Audit catches it, feeds diagnostic back, generator corrects query,
    audit passes on attempt 2, and executor runs the approved query.
    """
    schema, bundle, executor = setup_pipeline

    # Mock responses: attempt 1 misses status, attempt 2 corrects it
    backend = MockGeneratorBackend(
        responses={
            "department spend in 2024": (
                "SELECT d.name, sum(e.amount) as spend "
                "FROM departments d JOIN expenses e ON d.id = e.department_id "
                "WHERE e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
                "GROUP BY d.name;"
            ),
            "revised:expenses.status = 'approved'": (
                "SELECT d.name, sum(e.amount) as spend "
                "FROM departments d JOIN expenses e ON d.id = e.department_id "
                "WHERE e.status = 'approved' "
                "  AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
                "GROUP BY d.name;"
            ),
        }
    )
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )

    res = pipeline.run("What was department spend in 2024?")

    assert res.executed is True
    assert res.revisions_attempted == 1
    assert res.final_sql is not None
    assert "status = 'approved'" in res.final_sql.lower()
    assert res.execution_result is not None
    assert res.execution_result.success is True
    assert len(res.execution_result.rows) > 0
    # Verified audit trail recorded both stages
    audit_stages = [step["stage"] for step in res.audit_trail]
    assert "intent_classification" in audit_stages
    assert "retrieval" in audit_stages
    assert "rule_audit" in audit_stages
    assert "execution" in audit_stages


def test_revision_loop_fails_closed_on_persistent_violation(setup_pipeline):
    """
    Scenario 2: Generator refuses or fails to correct violation.
    Pipeline must abort after max_revisions and NEVER reach executor.
    """
    schema, bundle, executor = setup_pipeline

    # Persistent failure: query always uses forbidden substitute is_active
    backend = MockGeneratorBackend(
        default_response="SELECT count(*) FROM customers c WHERE c.is_active = 1;"
    )
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )

    res = pipeline.run("How many active customers do we have?", max_revisions=1)

    assert res.executed is False
    assert res.execution_result is None  # Never reached executor!
    assert res.revisions_attempted == 1
    assert "Rule compliance failure" in str(res.error_message)
    assert "forbidden substitute" in str(res.error_message).lower()


def test_guardrail_violation_aborts_immediately(setup_pipeline):
    """
    Scenario 3: Initial query contains an illegal mutation (e.g. DROP TABLE).
    Guardrail aborts immediately; no execution.
    """
    schema, bundle, executor = setup_pipeline

    backend = MockGeneratorBackend(
        default_response="DROP TABLE expenses; SELECT 1;"
    )
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )

    res = pipeline.run("What was the departmental spend in 2024?", max_revisions=1)

    assert res.executed is False
    assert res.execution_result is None
    assert res.guardrail_result is not None
    assert res.guardrail_result.is_valid is False
    assert "Guardrail violation" in str(res.error_message)


def test_ambiguous_question_early_exit(setup_pipeline):
    """
    Scenario 4: Ambiguous query ('spend') is caught by router before generation or execution.
    """
    schema, bundle, executor = setup_pipeline

    backend = MockGeneratorBackend()
    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )

    res = pipeline.run("spend")

    assert res.executed is False
    assert res.intent == IntentType.AMBIGUOUS
    assert res.clarification_prompt is not None
    assert len(backend.call_history) == 0  # LLM generator was never invoked!

