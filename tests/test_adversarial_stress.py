"""
Adversarial Stress Test Suite for Policy-Aware SQL Auditor.

Probes AnswerBuilder edge cases, RuleAuditor semantic evasion attempts,
fail-closed safety mechanisms, and extreme/adversarial inputs.
"""

import pytest
import sqlglot
from sqlglot import exp

from sql_auditor.config import DEFAULT_DB_PATH, KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.executor import ExecutionResult, SafeExecutor
from sql_auditor.rule_auditor import RuleAuditor, AuditStatus
from sql_auditor.sql_guardrails import validate_sql
from sql_auditor.answer_builder import AnswerBuilder, StructuredAnswer
from sql_auditor.pipeline import PipelineResult
from sql_auditor.router import IntentType


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(scope="module")
def schema():
    return inspect_schema(db_path=DEFAULT_DB_PATH)


@pytest.fixture(scope="module")
def bundle(schema):
    return load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)


@pytest.fixture(scope="module")
def auditor(schema):
    return RuleAuditor(schema=schema)


@pytest.fixture(scope="module")
def spend_rules(bundle):
    return [
        bundle.get("metric.departmental_spend"),
        bundle.get("policy.fiscal_year"),
        bundle.get("policy.expense_reimbursement"),
    ]


@pytest.fixture(scope="module")
def active_customer_rules(bundle):
    return [
        bundle.get("metric.active_customer"),
    ]


# ==============================================================================
# 1. AnswerBuilder Stress & Edge Cases
# ==============================================================================

class TestAnswerBuilderEdgeCases:
    """Stress tests for AnswerBuilder across edge conditions."""

    def test_zero_rows_returned(self):
        """Zero rows returned should produce polite conversational zero-record summary without crash."""
        exec_res = ExecutionResult(
            columns=["department", "spend"],
            rows=[],
            row_count=0,
            execution_time_ms=1.23,
            success=True,
        )
        pipeline_res = PipelineResult(
            question="What was spend for Legal in 2024?",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql="SELECT 'Legal', 0 WHERE 1=0;",
            execution_result=exec_res,
            retrieved_rule_ids=["metric.departmental_spend@v1"],
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert answer.status == "success"
        assert answer.row_count == 0
        assert "0 records" in answer.answer_summary
        assert "satisfied" in answer.answer_summary.lower() or "verified" in answer.answer_summary.lower()
        d = answer.to_dict()
        assert d["row_count"] == 0
        assert d["rows"] == []

    def test_single_row_returned(self):
        """Single row returned formats row key-values naturally with cited policy."""
        exec_res = ExecutionResult(
            columns=["spend"],
            rows=[{"spend": 450000.0}],
            row_count=1,
            execution_time_ms=0.85,
            success=True,
        )
        pipeline_res = PipelineResult(
            question="Engineering spend in 2024?",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql="SELECT sum(amount) FROM expenses;",
            execution_result=exec_res,
            retrieved_rule_ids=["metric.departmental_spend@v1"],
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert answer.status == "success"
        assert "spend: 450000.0" in answer.answer_summary
        assert "metric.departmental_spend@v1" in answer.answer_summary
        assert len(answer.policy_justifications) > 0
        assert answer.policy_justifications[0]["rule_id"] == "metric.departmental_spend"

    def test_multiple_rows_large_result(self):
        """Large multi-row result formats plural record summary without crashing."""
        rows = [{"dept": f"Dept_{i}", "val": i * 1000.0} for i in range(100)]
        exec_res = ExecutionResult(
            columns=["dept", "val"],
            rows=rows,
            row_count=100,
            execution_time_ms=12.5,
            truncated=True,
            success=True,
        )
        pipeline_res = PipelineResult(
            question="All department spend?",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql="SELECT d.name, sum(e.amount) FROM ...",
            execution_result=exec_res,
            retrieved_rule_ids=["metric.departmental_spend@v1"],
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert answer.status == "success"
        assert "100 records" in answer.answer_summary
        assert answer.truncated is True
        assert answer.row_count == 100

    def test_special_characters_in_row_data(self):
        """Row values with Unicode, emojis, newlines, HTML tags, and SQL code."""
        rows = [
            {
                "description": "Unicode: 财务支出 & 🚀",
                "notes": "Line1\nLine2\tTabbed",
                "xss": "<script>alert('pwned')</script>",
                "sqli": "'; DROP TABLE departments; --",
                "none_val": None,
                "bool_val": False,
            }
        ]
        exec_res = ExecutionResult(
            columns=list(rows[0].keys()),
            rows=rows,
            row_count=1,
            execution_time_ms=2.0,
            success=True,
        )
        pipeline_res = PipelineResult(
            question="Check descriptions",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql="SELECT * FROM expenses;",
            execution_result=exec_res,
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert answer.status == "success"
        assert "🚀" in answer.answer_summary
        assert "<script>" in answer.answer_summary
        # Verify JSON/dict serializability
        d = answer.to_dict()
        assert d["rows"][0]["none_val"] is None

    def test_missing_optional_parameters_and_none_handling(self):
        """PipelineResult with completely None optional fields should not crash."""
        pipeline_res = PipelineResult(
            question="Empty pipeline result?",
            intent=IntentType.METRIC_QUERY,
            executed=False,
            final_sql=None,
            execution_result=None,
            guardrail_result=None,
            rule_audit_result=None,
            retrieved_rule_ids=[],
            clarification_prompt=None,
            error_message=None,
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert answer.status == "error"
        assert "Unknown execution error" in answer.answer_summary
        assert answer.sql_query is None
        assert answer.cited_rules == []
        d = answer.to_dict()
        assert isinstance(d, dict)

    def test_unrecognized_custom_rules_in_justifications(self):
        """Custom/unrecognized rule tags should receive sensible graceful fallbacks."""
        pipeline_res = PipelineResult(
            question="Custom rule inquiry",
            intent=IntentType.METRIC_QUERY,
            executed=True,
            final_sql="SELECT 1;",
            execution_result=ExecutionResult(columns=["1"], rows=[{"1": 1}], row_count=1, execution_time_ms=1.0, success=True),
            retrieved_rule_ids=["custom.esg_governance_score@v2", "unversioned_rule"],
        )
        answer = AnswerBuilder.build_answer(pipeline_res)
        assert len(answer.policy_justifications) == 2
        j1 = answer.policy_justifications[0]
        assert j1["rule_id"] == "custom.esg_governance_score"
        assert j1["version"] == "2"
        assert "Esg Governance Score" in j1["title"]


# ==============================================================================
# 2. RuleAuditor Adversarial Evasion Probes
# ==============================================================================

class TestRuleAuditorEvasionProbes:
    """Stress tests probing whether RuleAuditor can be fooled by evasion patterns."""

    def test_casing_variations_on_status_filter(self, auditor, spend_rules):
        """Probe: status = 'APPROVED' (all caps) vs 'approved'."""
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE e.status = 'APPROVED'
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        # Value comparison should be case-insensitive
        assert res.is_compliant is True, f"Failed on upper-case status: {res.summary_message()}"

    def test_symmetric_equality_literal_first(self, auditor, spend_rules):
        """Probe: 'approved' = e.status (symmetric equality)."""
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE 'approved' = e.status
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is True, f"Failed symmetric equality: {res.summary_message()}"

    def test_table_alias_evasion_complex_name(self, auditor, spend_rules):
        """Probe: non-standard table alias (e.g. exp_tab_2024)."""
        sql = """
            SELECT d.name, SUM(exp_tab_2024.amount) AS total_spend
            FROM departments d
            JOIN expenses AS exp_tab_2024 ON d.id = exp_tab_2024.department_id
            WHERE exp_tab_2024.status = 'approved'
              AND exp_tab_2024.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is True, f"Failed custom alias: {res.summary_message()}"

    def test_in_clause_with_only_approved(self, auditor, spend_rules):
        """Probe: status IN ('approved') single value in IN clause."""
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE e.status IN ('approved')
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is True, f"Failed single IN clause: {res.summary_message()}"

    def test_probe_in_clause_mixed_approved_and_pending_violation(self, auditor, spend_rules):
        """
        Adversarial probe: e.status IN ('approved', 'pending')
        ATTACK: Candidate query allows pending expenses alongside approved!
        RuleAuditor must reject multi-value IN clauses containing unapproved values.
        """
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE e.status IN ('approved', 'pending')
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False, "VULNERABILITY: RuleAuditor accepted multi-value IN ('approved', 'pending')"

    def test_probe_disjunctive_or_injection(self, auditor, spend_rules):
        """
        Adversarial probe: WHERE (e.status = 'approved' OR 1=1)
        ATTACK: Attacker injects OR 1=1 to bypass the filter and include unapproved expenses!
        RuleAuditor must reject predicates guarded by OR.
        """
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE (e.status = 'approved' OR 1=1)
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False, "VULNERABILITY: RuleAuditor accepted disjunctive OR 1=1 bypass"

    def test_probe_negation_attack(self, auditor, spend_rules):
        """
        Adversarial probe: WHERE NOT (e.status = 'approved')
        ATTACK: Attacker negates the required condition!
        RuleAuditor must reject conditions under NOT.
        """
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE NOT (e.status = 'approved')
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False, "VULNERABILITY: RuleAuditor accepted NOT (e.status = 'approved')"

    def test_probe_inequality_instead_of_equality(self, auditor, spend_rules):
        """
        Adversarial probe: WHERE e.status != 'rejected'
        Should FAIL because status must equal 'approved', not merely 'not rejected'.
        """
        sql = """
            SELECT d.name, SUM(e.amount) AS total_spend
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE e.status != 'rejected'
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False
        assert any(v.violation_type == "MISSING_FILTER" for v in res.violations)

    def test_forbidden_substitute_unqualified_column(self, auditor, active_customer_rules):
        """
        Adversarial probe: SELECT is_active FROM customers
        Should be detected as FORBIDDEN_SUBSTITUTE even without table prefix.
        """
        sql = "SELECT id, name, is_active FROM customers;"
        res = auditor.audit(sql, rules=active_customer_rules)
        assert res.is_compliant is False
        assert any(v.violation_type == "FORBIDDEN_SUBSTITUTE" for v in res.violations)

    def test_forbidden_substitute_in_where_clause(self, auditor, active_customer_rules):
        """
        Adversarial probe: WHERE c.is_active = 1
        """
        sql = "SELECT c.id, c.name FROM customers c WHERE c.is_active = 1;"
        res = auditor.audit(sql, rules=active_customer_rules)
        assert res.is_compliant is False
        assert any(v.violation_type == "FORBIDDEN_SUBSTITUTE" for v in res.violations)

    def test_forbidden_substitute_in_subquery(self, auditor, active_customer_rules):
        """
        Adversarial probe: SELECT * FROM (SELECT is_active FROM customers)
        """
        sql = "SELECT * FROM (SELECT is_active FROM customers);"
        res = auditor.audit(sql, rules=active_customer_rules)
        assert res.is_compliant is False
        assert any(v.violation_type == "FORBIDDEN_SUBSTITUTE" for v in res.violations)

    def test_missing_date_bounds_wrong_year(self, auditor, spend_rules):
        """
        Fiscal year mismatch: context requires 2024, query has 2023 dates.
        """
        sql = """
            SELECT d.name, SUM(e.amount)
            FROM departments d
            JOIN expenses e ON d.id = e.department_id
            WHERE e.status = 'approved'
              AND e.expense_date BETWEEN '2023-01-01' AND '2023-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False
        assert any(v.violation_type == "MISSING_DATE_BOUNDS" for v in res.violations)

    def test_missing_join_cartesian_product(self, auditor, spend_rules):
        """
        Query has both departments and expenses in FROM, but no ON condition or WHERE join.
        """
        sql = """
            SELECT d.name, SUM(e.amount)
            FROM departments d, expenses e
            WHERE e.status = 'approved'
              AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
            GROUP BY d.name;
        """
        res = auditor.audit(sql, rules=spend_rules, context={"fiscal_year": 2024})
        assert res.is_compliant is False
        assert any(v.violation_type == "MISSING_JOIN" for v in res.violations)


# ==============================================================================
# 3. Fail-Closed Safety Guardrails Probes
# ==============================================================================

class TestSafetyGuardrailFailClosed:
    """Stress tests probing whether guardrails fail closed on hostile queries."""

    def test_stacked_query_injection(self, schema):
        """Semicolon stacked query injection must fail closed."""
        res = validate_sql("SELECT * FROM departments; DROP TABLE departments;", schema=schema)
        assert res.is_valid is False
        assert "Multiple SQL statements" in res.error_message

    def test_disallowed_extension_function(self, schema):
        """Call to load_extension or writefile must fail closed."""
        res = validate_sql("SELECT load_extension('shell.dll');", schema=schema)
        assert res.is_valid is False
        assert "Disallowed function" in res.error_message

    def test_cte_mutating_statement_disguise(self, schema):
        """Mutating CTE (DELETE/INSERT) disguised as SELECT must fail closed."""
        sql = "WITH deleted AS (DELETE FROM departments RETURNING *) SELECT * FROM deleted;"
        res = validate_sql(sql, schema=schema)
        assert res.is_valid is False

    def test_unallowlisted_table(self, schema):
        """Accessing system or non-allowlisted table must fail closed."""
        res = validate_sql("SELECT * FROM sqlite_master;", schema=schema)
        assert res.is_valid is False
        assert "Unknown table" in res.error_message

    def test_unallowlisted_column(self, schema):
        """Accessing nonexistent column must fail closed."""
        res = validate_sql("SELECT password_hash FROM departments;", schema=schema)
        assert res.is_valid is False
        assert "Unknown column" in res.error_message
