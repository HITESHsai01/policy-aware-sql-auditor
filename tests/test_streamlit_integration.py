"""
End-to-End Integration and Verification Tests for Streamlit Dashboard and Core Pipeline (R3).

Verifies the integration between app.py, dashboard.py, AuditorPipeline, AnswerBuilder,
and AuditLogger across the five core governance scenarios:
1. Compliant spend metric execution with rule citations.
2. Rule-trap missing filter with automatic iterative revision repair.
3. Forbidden substitute query rejected fail-closed with governance rationale.
4. Adversarial SQL injection query blocked by AST guardrails fail-closed.
5. Ambiguous query caught by intent router returning clarification prompt.
"""

import os
from pathlib import Path
import py_compile
import tempfile
import pytest

from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.executor import SafeExecutor
from sql_auditor.sql_generator import SQLGenerator, MockGeneratorBackend
from sql_auditor.pipeline import AuditorPipeline, IntentType
from sql_auditor.answer_builder import AnswerBuilder
from sql_auditor.audit_log import AuditLogger
from sql_auditor.dashboard import (
    PRESET_QUERIES,
    extract_revision_history,
    get_pipeline_and_components,
)


def test_dashboard_and_app_syntax_compilation():
    """Verify app.py and dashboard.py compile to bytecode with zero syntax errors."""
    root_dir = Path(__file__).resolve().parent.parent
    app_path = root_dir / "app.py"
    dashboard_path = root_dir / "src" / "sql_auditor" / "dashboard.py"

    assert app_path.exists(), f"app.py does not exist at {app_path}"
    assert dashboard_path.exists(), f"dashboard.py does not exist at {dashboard_path}"

    app_pyc = py_compile.compile(str(app_path), doraise=True)
    assert app_pyc is not None, "Failed to compile app.py"

    dashboard_pyc = py_compile.compile(str(dashboard_path), doraise=True)
    assert dashboard_pyc is not None, "Failed to compile dashboard.py"


def test_dashboard_imports_and_exports():
    """Verify dashboard functions and classes import cleanly without exceptions."""
    from sql_auditor.dashboard import run_dashboard, get_pipeline_and_components, PRESET_QUERIES
    assert callable(run_dashboard)
    assert callable(get_pipeline_and_components)
    assert len(PRESET_QUERIES) == 5


def test_dashboard_preset_queries_structure():
    """Verify that all 5 curated presets contain valid schemas and questions."""
    expected_categories = [
        "Compliant Spend Metric",
        "Missing Filter with Auto-Repair",
        "Forbidden Substitute with Rejection",
        "Adversarial SQL Injection with Security Block",
        "Ambiguous Query with Clarification",
    ]
    assert len(PRESET_QUERIES) == 5
    for preset in PRESET_QUERIES:
        assert "id" in preset
        assert "category" in preset
        assert preset["category"] in expected_categories
        assert "icon" in preset
        assert "label" in preset
        assert "question" in preset and len(preset["question"].strip()) > 0
        assert "fiscal_year" in preset
        assert "description" in preset


def test_get_pipeline_and_components_initialization():
    """Verify that get_pipeline_and_components correctly initializes and returns typed components."""
    pipeline, logger, schema, bundle = get_pipeline_and_components(
        db_path_str=str(DEFAULT_DB_PATH),
        knowledge_dir_str=str(KNOWLEDGE_DIR),
        backend_type="mock",
    )
    assert pipeline is not None
    assert logger is not None
    assert schema is not None
    assert bundle is not None
    assert len(schema.tables) >= 5
    assert len(bundle.concepts) >= 9


@pytest.fixture
def integrated_pipeline(tmp_path):
    """Initializes end-to-end pipeline with dedicated temporary audit logger."""
    test_audit_db = tmp_path / "test_auditor.db"
    schema = inspect_schema(db_path=DEFAULT_DB_PATH)
    bundle = load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)
    executor = SafeExecutor(db_path=DEFAULT_DB_PATH)

    backend = MockGeneratorBackend(
        responses={
            "departmental spend for engineering in 2024": (
                "SELECT d.name, sum(e.amount) as spend "
                "FROM departments d JOIN expenses e ON d.id = e.department_id "
                "WHERE d.name = 'Engineering' "
                "  AND e.status = 'approved' "
                "  AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31' "
                "GROUP BY d.name;"
            ),
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
            "drop table": "DROP TABLE departments;",
        }
    )

    generator = SQLGenerator(backend=backend, schema=schema)
    pipeline = AuditorPipeline(
        schema=schema,
        bundle=bundle,
        generator=generator,
        executor=executor,
    )
    logger = AuditLogger(db_path=test_audit_db)
    return pipeline, logger


def test_scenario_a_compliant_spend_metric(integrated_pipeline):
    """Scenario A: Standard compliant spend metric query executes and logs cleanly."""
    pipeline, logger = integrated_pipeline
    question = "What was the departmental spend for Engineering in 2024?"
    result = pipeline.run(question=question, context={"fiscal_year": 2024})

    assert result.executed is True
    assert result.revisions_attempted == 0
    assert result.execution_result is not None
    assert result.execution_result.success is True
    assert len(result.execution_result.rows) > 0

    # Humanizer Answer Verification
    answer = AnswerBuilder.build_answer(result)
    assert answer.status == "success"
    assert "metric.departmental_spend@v1" in answer.cited_rules
    assert answer.explanation is not None
    assert len(answer.rows) > 0

    # Audit Logging Verification
    record = logger.log_result(result)
    assert record.executed is True
    assert record.rule_audit_status == "PASS"
    assert record.guardrail_status == "PASS"


def test_scenario_b_missing_filter_auto_repair(integrated_pipeline):
    """Scenario B: Query missing approved status is caught and auto-repaired in revision loop."""
    pipeline, logger = integrated_pipeline
    question = "What was department spend in 2024?"
    result = pipeline.run(question=question, context={"fiscal_year": 2024}, max_revisions=1)

    assert result.executed is True
    assert result.revisions_attempted == 1
    assert result.final_sql is not None
    assert "status = 'approved'" in result.final_sql.lower()
    assert result.execution_result is not None
    assert result.execution_result.success is True

    # Revision comparison helper in dashboard
    rev_info = extract_revision_history(result.audit_trail, result.final_sql)
    assert rev_info is not None
    assert rev_info["attempt_1_status"] == "FAIL"
    assert rev_info["attempt_2_status"] == "PASS"
    assert "status = 'approved'" in rev_info["attempt_2_sql"].lower()

    # Log verification
    record = logger.log_result(result)
    assert record.revisions_attempted == 1
    assert record.executed is True


def test_scenario_c_forbidden_substitute_rejected(integrated_pipeline):
    """Scenario C: Query attempting deprecated proxy flag is rejected fail-closed."""
    pipeline, logger = integrated_pipeline
    # Register mock backend response returning forbidden substitute
    pipeline.generator.backend.set_response(
        "active customers",
        "SELECT count(*) FROM customers c WHERE c.is_active = 1;",
    )
    pipeline.generator.backend.default_response = "SELECT count(*) FROM customers c WHERE c.is_active = 1;"
    question = "List active customers using the is_active flag."
    result = pipeline.run(question=question, max_revisions=0)

    assert result.executed is False
    assert result.execution_result is None
    assert result.rule_audit_result is not None
    assert result.rule_audit_result.is_compliant is False

    violation_types = [v.violation_type for v in result.rule_audit_result.violations]
    assert "FORBIDDEN_SUBSTITUTE" in violation_types

    # Humanizer Answer Verification
    answer = AnswerBuilder.build_answer(result)
    assert answer.status == "rejected_rule_violation"
    assert "rejected due to business compliance failure" in answer.answer_summary
    assert len(answer.policy_justifications) > 0

    # Audit Logging Verification
    record = logger.log_result(result)
    assert record.executed is False
    assert record.rule_audit_status == "FAIL"


def test_scenario_d_adversarial_injection_blocked_fail_closed(integrated_pipeline):
    """Scenario D: Destructive query is blocked immediately by AST guardrails."""
    pipeline, logger = integrated_pipeline
    question = "DROP TABLE departments;"
    result = pipeline.run(question=question, max_revisions=1)

    assert result.executed is False
    assert result.execution_result is None
    assert result.guardrail_result is not None
    assert result.guardrail_result.is_valid is False
    assert "Drop" in str(result.guardrail_result.error_message)

    # Humanizer Answer Verification
    answer = AnswerBuilder.build_answer(result)
    assert answer.status == "rejected_guardrail_violation"
    assert "rejected by safety guardrails" in answer.answer_summary

    # Audit Logging Verification
    record = logger.log_result(result)
    assert record.executed is False
    assert record.guardrail_status == "FAIL"


def test_scenario_e_ambiguous_query_clarification(integrated_pipeline):
    """Scenario E: Underspecified inquiry is intercepted by router before SQL generation."""
    pipeline, logger = integrated_pipeline
    question = "Show me the spend"
    result = pipeline.run(question=question)

    assert result.executed is False
    assert result.intent == IntentType.AMBIGUOUS
    assert result.clarification_prompt is not None
    assert result.final_sql is None

    # Humanizer Answer Verification
    answer = AnswerBuilder.build_answer(result)
    assert answer.status == "ambiguous"
    assert answer.clarification_prompt is not None

    # Audit Logging Verification
    record = logger.log_result(result)
    assert record.executed is False
    assert record.intent == "ambiguous"


def test_audit_logger_query_persistence(integrated_pipeline):
    """Verify that multiple logged results persist in SQLite and are retrievable."""
    pipeline, logger = integrated_pipeline

    # Submit 3 distinct queries
    res1 = pipeline.run("What was the departmental spend for Engineering in 2024?", context={"fiscal_year": 2024})
    res2 = pipeline.run("Show me the spend")
    res3 = pipeline.run("DROP TABLE departments;")

    logger.log_result(res1)
    logger.log_result(res2)
    logger.log_result(res3)

    recent_records = logger.get_recent_records(limit=10)
    assert len(recent_records) >= 3

    questions = [r.question for r in recent_records]
    assert "What was the departmental spend for Engineering in 2024?" in questions
    assert "Show me the spend" in questions
    assert "DROP TABLE departments;" in questions
