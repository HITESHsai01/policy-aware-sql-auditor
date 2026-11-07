"""
Unit tests for Deterministic SQL Guardrails (sql_guardrails.py).
"""

import pytest
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.sql_guardrails import validate_sql


@pytest.fixture(scope="module")
def schema():
    return inspect_schema()


def test_valid_simple_select(schema):
    sql = "SELECT id, name FROM departments;"
    res = validate_sql(sql, schema=schema)
    assert res.is_valid, f"Unexpected failure: {res.error_message}"
    assert "departments" in res.tables
    assert "id" in res.columns
    assert "name" in res.columns


def test_valid_join_query(schema):
    sql = """
        SELECT d.name, SUM(e.amount) AS total_spend
        FROM departments d
        JOIN expenses e ON d.id = e.department_id
        WHERE e.status = 'approved'
        GROUP BY d.name;
    """
    res = validate_sql(sql, schema=schema)
    assert res.is_valid, f"Unexpected failure: {res.error_message}"
    assert "departments" in res.tables
    assert "expenses" in res.tables
    assert "name" in res.columns
    assert "amount" in res.columns
    assert "status" in res.columns


def test_valid_cte_query(schema):
    sql = """
        WITH dept_expenses AS (
            SELECT department_id, SUM(amount) AS total_amt
            FROM expenses
            WHERE status = 'approved'
            GROUP BY department_id
        )
        SELECT d.name, de.total_amt
        FROM departments d
        JOIN dept_expenses de ON d.id = de.department_id;
    """
    res = validate_sql(sql, schema=schema)
    assert res.is_valid, f"Unexpected failure: {res.error_message}"
    assert "departments" in res.tables
    assert "expenses" in res.tables


def test_reject_multiple_statements(schema):
    sql = "SELECT id FROM departments; SELECT * FROM expenses;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "multiple" in res.error_message.lower()


def test_reject_insert_mutation(schema):
    sql = "INSERT INTO departments (name) VALUES ('Hacking');"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "Disallowed statement type" in res.error_message or "mutating" in res.error_message.lower()


def test_reject_update_mutation(schema):
    sql = "UPDATE expenses SET amount = 0 WHERE id = 1;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "Disallowed statement type" in res.error_message or "mutating" in res.error_message.lower()


def test_reject_delete_mutation(schema):
    sql = "DELETE FROM expenses WHERE id = 1;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "Disallowed statement type" in res.error_message or "mutating" in res.error_message.lower()


def test_reject_ddl_drop(schema):
    sql = "DROP TABLE departments;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "Disallowed statement type" in res.error_message or "mutating" in res.error_message.lower()


def test_reject_ddl_create(schema):
    sql = "CREATE TABLE backdoor (id INT);"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid


def test_reject_mutating_cte(schema):
    sql = """
        WITH hacked AS (
            DELETE FROM expenses RETURNING id
        )
        SELECT * FROM hacked;
    """
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "mutating" in res.error_message.lower() or "disallowed" in res.error_message.lower()


def test_reject_unknown_table(schema):
    sql = "SELECT * FROM salaries;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "unknown table 'salaries'" in res.error_message.lower()


def test_reject_unknown_column_qualified(schema):
    sql = "SELECT expenses.credit_card_number FROM expenses;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "unknown column 'credit_card_number'" in res.error_message.lower()


def test_reject_unknown_column_unqualified(schema):
    sql = "SELECT secret_pin FROM expenses;"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "unknown column 'secret_pin'" in res.error_message.lower()


def test_reject_disallowed_function(schema):
    sql = "SELECT load_extension('malicious.dll');"
    res = validate_sql(sql, schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "disallowed function" in res.error_message.lower()


def test_reject_empty_sql(schema):
    res = validate_sql("   ", schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "empty" in res.error_message.lower()


def test_reject_malformed_syntax(schema):
    res = validate_sql("SELECT FROM WHERE ;", schema=schema)
    assert not res.is_valid
    assert res.error_message is not None
    assert "parse" in res.error_message.lower() or "syntax" in res.error_message.lower()

