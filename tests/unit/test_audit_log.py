"""
Unit tests for Audit Logger (audit_log.py).
"""

from pathlib import Path
import pytest
from sql_auditor.audit_log import AuditLogger, AuditRecord
from sql_auditor.pipeline import PipelineResult
from sql_auditor.router import IntentType
from sql_auditor.sql_guardrails import GuardrailResult
from sql_auditor.rule_auditor import RuleAuditResult, AuditStatus, RuleViolation
from sql_auditor.executor import ExecutionResult


@pytest.fixture
def logger(tmp_path):
    test_db = tmp_path / "test_audit.db"
    return AuditLogger(db_path=test_db)


def test_audit_log_success_record(logger):
    pipe_res = PipelineResult(
        question="What was spend in 2024?",
        intent=IntentType.METRIC_QUERY,
        executed=True,
        final_sql="SELECT sum(amount) FROM expenses WHERE status='approved';",
        execution_result=ExecutionResult(
            success=True,
            columns=["sum(amount)"],
            rows=[{"sum(amount)": 450000.0}],
            row_count=1,
            execution_time_ms=1.5,
        ),
        guardrail_result=GuardrailResult(is_valid=True),
        rule_audit_result=RuleAuditResult(
            status=AuditStatus.PASS,
            passed_rules=["metric.departmental_spend@v1"],
        ),
        retrieved_rule_ids=["metric.departmental_spend@v1"],
        revisions_attempted=0,
    )

    record = logger.log_result(pipe_res)
    assert record.request_id is not None
    assert record.executed is True
    assert record.guardrail_status == "PASS"
    assert record.rule_audit_status == "PASS"
    assert record.row_count == 1
    assert record.execution_time_ms == 1.5
    assert record.retrieved_rules == ["metric.departmental_spend@v1"]


def test_audit_log_rejection_record(logger):
    pipe_res = PipelineResult(
        question="Compute spend",
        intent=IntentType.METRIC_QUERY,
        executed=False,
        final_sql="SELECT sum(amount) FROM expenses;",
        guardrail_result=GuardrailResult(is_valid=True),
        rule_audit_result=RuleAuditResult(
            status=AuditStatus.FAIL,
            violations=[
                RuleViolation(
                    rule_id="metric.departmental_spend",
                    rule_version=1,
                    violation_type="MISSING_FILTER",
                    message="Missing required filter: expenses.status = 'approved'.",
                )
            ],
        ),
        retrieved_rule_ids=["metric.departmental_spend@v1"],
        revisions_attempted=1,
        error_message="Rule compliance failure",
    )

    record = logger.log_result(pipe_res, request_id="custom-req-123")
    assert record.request_id == "custom-req-123"
    assert record.executed is False
    assert record.rule_audit_status == "FAIL"
    assert len(record.rule_violations) == 1
    assert "expenses.status = 'approved'" in record.rule_violations[0]


def test_get_recent_records_and_lookup_by_id(logger):
    # Log 3 records
    for i in range(3):
        res = PipelineResult(
            question=f"Question {i}",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql=f"SELECT {i};",
            execution_result=ExecutionResult(success=True, row_count=1, execution_time_ms=0.5),
            retrieved_rule_ids=["rule@v1"],
        )
        logger.log_result(res, request_id=f"req-{i}")

    recent = logger.get_recent_records(limit=2)
    assert len(recent) == 2

    single = logger.get_record("req-1")
    assert single is not None
    assert single.question == "Question 1"

    missing = logger.get_record("non-existent-id")
    assert missing is None

