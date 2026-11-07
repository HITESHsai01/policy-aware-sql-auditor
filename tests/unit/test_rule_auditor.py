"""
Unit tests for Deterministic Rule-Compliance Auditor (rule_auditor.py).
"""

import pytest
from sql_auditor.config import KNOWLEDGE_DIR
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.knowledge_loader import load_knowledge_bundle
from sql_auditor.rule_auditor import RuleAuditor, AuditStatus


@pytest.fixture(scope="module")
def schema():
    return inspect_schema()


@pytest.fixture(scope="module")
def bundle(schema):
    return load_knowledge_bundle(knowledge_dir=KNOWLEDGE_DIR, schema=schema)


@pytest.fixture(scope="module")
def auditor(schema):
    return RuleAuditor(schema=schema)


def test_audit_passes_valid_departmental_spend(auditor, bundle):
    rules = [
        bundle.get("metric.departmental_spend"),
        bundle.get("policy.fiscal_year"),
        bundle.get("policy.expense_reimbursement"),
    ]
    sql = """
        SELECT d.name, SUM(e.amount) AS total_spend
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS
    assert res.is_compliant is True
    assert len(res.violations) == 0
    assert "metric.departmental_spend@v1" in res.passed_rules


def test_audit_fails_missing_approved_status_filter(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    # Query has date filter but omits status='approved'
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    assert res.is_compliant is False
    v_messages = [v.message for v in res.violations]
    assert any("expenses.status = 'approved'" in m for m in v_messages)


def test_audit_fails_missing_fiscal_year_date_bounds(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend"), bundle.get("policy.fiscal_year")]
    # Query has status='approved' but no date bounds
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.status = 'approved'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    v_messages = [v.message for v in res.violations]
    assert any("fiscal year date boundary" in m.lower() for m in v_messages)


def test_audit_predicate_normalization_in_clause(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    # Uses e.status IN ('approved') instead of e.status = 'approved'
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.status IN ('approved')
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS


def test_audit_predicate_normalization_strftime_date(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    # Uses strftime('%Y', e.expense_date) = '2024'
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.status = 'approved'
          AND strftime('%Y', e.expense_date) = '2024'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS


def test_audit_fails_forbidden_substitute_is_active(auditor, bundle):
    rules = [bundle.get("metric.active_customer")]
    # AI incorrectly uses customers.is_active = 1
    sql = "SELECT count(*) FROM customers c WHERE c.is_active = 1;"
    res = auditor.audit(sql, rules=rules)
    assert res.status == AuditStatus.FAIL
    types = [v.violation_type for v in res.violations]
    assert "FORBIDDEN_SUBSTITUTE" in types
    messages = [v.message for v in res.violations]
    assert any("customers.is_active" in m for m in messages)


def test_audit_passes_valid_active_customer(auditor, bundle):
    rules = [bundle.get("metric.active_customer")]
    sql = """
        SELECT count(DISTINCT c.id)
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        WHERE o.status = 'completed'
          AND o.order_date >= '2025-01-01';
    """
    res = auditor.audit(sql, rules=rules)
    assert res.status == AuditStatus.PASS
    assert res.is_compliant is True


def test_audit_alias_resolution(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    # Uses unadorned alias 'exp'
    sql = """
        SELECT d.name, SUM(exp.amount)
        FROM departments d
        JOIN expenses exp ON d.id = exp.department_id
        WHERE exp.status = 'approved'
          AND exp.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS


def test_audit_unqualified_column_resolution(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    # Uses unqualified 'status' and 'expense_date'
    sql = """
        SELECT d.name, SUM(expenses.amount)
        FROM departments d
        JOIN expenses ON d.id = expenses.department_id
        WHERE status = 'approved'
          AND expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS


def test_audit_fails_cross_table_column_confusion(auditor, bundle):
    """Ensure orders.status='approved' does NOT satisfy required expenses.status='approved'."""
    rules = [bundle.get("metric.departmental_spend")]
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        JOIN orders o ON d.id = o.customer_id
        WHERE o.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    assert res.is_compliant is False
    assert any("expenses.status" in v.message for v in res.violations)


def test_audit_where_join_equality_passes(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d, expenses e
        WHERE d.id = e.department_id
          AND e.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.PASS


def test_audit_where_cartesian_product_fails(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d, expenses e
        WHERE d.name = 'Engineering'
          AND e.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    assert any(v.violation_type == "MISSING_JOIN" for v in res.violations)


def test_audit_where_join_guarded_by_or_fails(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d, expenses e
        WHERE (d.id = e.department_id OR 1 = 1)
          AND e.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    assert any(v.violation_type == "MISSING_JOIN" for v in res.violations)


def test_audit_where_join_guarded_by_not_fails(auditor, bundle):
    rules = [bundle.get("metric.departmental_spend")]
    sql = """
        SELECT d.name, SUM(e.amount)
        FROM departments d, expenses e
        WHERE NOT (d.id = e.department_id)
          AND e.status = 'approved'
          AND e.expense_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY d.name;
    """
    res = auditor.audit(sql, rules=rules, context={"fiscal_year": 2024})
    assert res.status == AuditStatus.FAIL
    assert any(v.violation_type == "MISSING_JOIN" for v in res.violations)



