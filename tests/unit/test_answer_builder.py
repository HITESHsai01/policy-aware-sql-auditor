"""
Unit tests for Answer Builder (answer_builder.py).
"""

from sql_auditor.answer_builder import AnswerBuilder
from sql_auditor.pipeline import PipelineResult
from sql_auditor.router import IntentType
from sql_auditor.sql_guardrails import GuardrailResult
from sql_auditor.rule_auditor import RuleAuditResult, AuditStatus, RuleViolation
from sql_auditor.executor import ExecutionResult


def test_answer_builder_success():
    res = PipelineResult(
        question="What was spend in 2024?",
        intent=IntentType.METRIC_QUERY,
        executed=True,
        final_sql="SELECT sum(amount) FROM expenses WHERE status='approved';",
        execution_result=ExecutionResult(
            success=True,
            columns=["spend"],
            rows=[{"spend": 450000.0}],
            row_count=1,
            execution_time_ms=1.2,
        ),
        retrieved_rule_ids=["metric.departmental_spend@v1"],
    )

    ans = AnswerBuilder.build_answer(res)
    assert ans.status == "success"
    assert ans.row_count == 1
    assert ans.columns == ["spend"]
    assert ans.rows[0]["spend"] == 450000.0
    assert "spend: 450000.0" in ans.answer_summary
    assert "metric.departmental_spend@v1" in ans.cited_rules


def test_answer_builder_rule_violation():
    res = PipelineResult(
        question="What was spend?",
        intent=IntentType.METRIC_QUERY,
        executed=False,
        final_sql="SELECT sum(amount) FROM expenses;",
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
    )

    ans = AnswerBuilder.build_answer(res)
    assert ans.status == "rejected_rule_violation"
    assert "rejected due to business compliance failure" in ans.answer_summary
    assert "expenses.status = 'approved'" in ans.answer_summary


def test_answer_builder_guardrail_violation():
    res = PipelineResult(
        question="Drop tables",
        intent=IntentType.METRIC_QUERY,
        executed=False,
        final_sql="DROP TABLE expenses;",
        guardrail_result=GuardrailResult(
            is_valid=False,
            error_message="Disallowed statement type: Drop.",
        ),
    )

    ans = AnswerBuilder.build_answer(res)
    assert ans.status == "rejected_guardrail_violation"
    assert "rejected by safety guardrails" in ans.answer_summary


def test_answer_builder_ambiguous():
    res = PipelineResult(
        question="spend",
        intent=IntentType.AMBIGUOUS,
        executed=False,
        clarification_prompt="Please specify department and fiscal year.",
    )

    ans = AnswerBuilder.build_answer(res)
    assert ans.status == "ambiguous"
    assert ans.clarification_prompt == "Please specify department and fiscal year."
    assert "Please specify" in ans.answer_summary


def test_answer_builder_unsupported():
    res = PipelineResult(
        question="What is bitcoin?",
        intent=IntentType.UNSUPPORTED,
        executed=False,
        clarification_prompt="This system only supports corporate financial data.",
    )

    ans = AnswerBuilder.build_answer(res)
    assert ans.status == "unsupported"
    assert "only supports corporate financial data" in ans.answer_summary

