"""
Unit tests for Safe Read-Only Executor (executor.py).
"""

from pathlib import Path
import pytest
from sql_auditor.config import DEFAULT_DB_PATH
from sql_auditor.executor import SafeExecutor, execute_read_only


@pytest.fixture(scope="module")
def executor():
    return SafeExecutor(db_path=DEFAULT_DB_PATH)


def test_execute_valid_select(executor):
    res = executor.execute("SELECT id, name FROM departments ORDER BY id ASC;")
    assert res.success is True
    assert res.error_message is None
    assert len(res.rows) == 5
    assert res.columns == ["id", "name"]
    assert res.rows[0]["name"] == "Engineering"
    assert res.execution_time_ms >= 0


def test_execute_read_only_blocks_write_at_sqlite_level(executor):
    """Even if an INSERT bypasses guardrails, SQLite mode=ro must block it."""
    res = executor.execute("INSERT INTO departments (id, name) VALUES (99, 'HackerDept');")
    assert res.success is False
    assert res.error_message is not None
    assert "readonly" in res.error_message.lower() or "read-only" in res.error_message.lower() or "attempt to write" in res.error_message.lower()


def test_row_truncation_limit(executor):
    """When query results exceed max_rows, truncate and flag truncated=True."""
    res = executor.execute("SELECT * FROM expenses;", max_rows=5)
    assert res.success is True
    assert len(res.rows) == 5
    assert res.truncated is True


def test_no_row_truncation_when_under_limit(executor):
    res = executor.execute("SELECT * FROM departments;", max_rows=100)
    assert res.success is True
    assert len(res.rows) == 5
    assert res.truncated is False


def test_execution_timeout_interrupts_query(executor):
    """An infinite recursive CTE must be cleanly interrupted by timeout."""
    infinite_query = """
        WITH RECURSIVE cnt(x) AS (
            SELECT 1
            UNION ALL
            SELECT x + 1 FROM cnt
        )
        SELECT COUNT(*) FROM cnt;
    """
    res = executor.execute(infinite_query, timeout_seconds=0.1)
    assert res.success is False
    assert res.error_message is not None
    assert "timed out" in res.error_message.lower() or "interrupted" in res.error_message.lower()


def test_nonexistent_database():
    bad_executor = SafeExecutor(db_path=Path("nonexistent_path/fake.db"))
    res = bad_executor.execute("SELECT 1;")
    assert res.success is False
    assert "does not exist" in res.error_message.lower()


def test_convenience_execute_read_only():
    res = execute_read_only("SELECT count(*) as cnt FROM budgets;")
    assert res.success is True
    assert res.rows[0]["cnt"] == 15

