"""
Safety and Attack Vector Tests for Deterministic SQL Guardrails.

Verifies that 15+ malicious injection, stacked queries, mutating subqueries,
administrative commands, and privilege escalation attempts are strictly blocked.
"""

import pytest
from sql_auditor.schema_inspector import inspect_schema
from sql_auditor.sql_guardrails import validate_sql


@pytest.fixture(scope="module")
def schema():
    return inspect_schema()


ATTACK_VECTORS = [
    # 1. Stacked query: DROP TABLE
    ("SELECT * FROM departments; DROP TABLE expenses;", "Stacked DROP TABLE"),

    # 2. Stacked query: INSERT admin row
    ("SELECT * FROM departments; INSERT INTO departments VALUES (999, 'EvilCorp');", "Stacked INSERT"),

    # 3. Stacked administrative PRAGMA tampering
    ("SELECT * FROM departments; PRAGMA foreign_keys = OFF;", "Stacked PRAGMA override"),

    # 4. Standalone DDL: DROP TABLE
    ("DROP TABLE expenses;", "Direct DROP TABLE"),

    # 5. Standalone DDL: ALTER TABLE
    ("ALTER TABLE expenses ADD COLUMN secret TEXT;", "Direct ALTER TABLE"),

    # 6. Standalone DDL: CREATE TABLE backdoor
    ("CREATE TABLE backdoor (cmd TEXT);", "Direct CREATE TABLE"),

    # 7. Standalone DML: DELETE all rows
    ("DELETE FROM expenses WHERE 1=1;", "Direct DELETE"),

    # 8. Standalone DML: TRUNCATE table
    ("TRUNCATE TABLE expenses;", "Direct TRUNCATE"),

    # 9. Standalone DML: UPDATE values
    ("UPDATE budgets SET approved_amount = 99999999;", "Direct UPDATE"),

    # 10. Mutating CTE trying to disguise DELETE as SELECT
    ("WITH payload AS (DELETE FROM expenses RETURNING id) SELECT * FROM payload;", "Mutating CTE with DELETE"),

    # 11. Mutating CTE trying to disguise INSERT as SELECT
    ("WITH payload AS (INSERT INTO departments (id, name) VALUES (100, 'Infiltrate') RETURNING id) SELECT * FROM payload;", "Mutating CTE with INSERT"),

    # 12. SQLite extension code execution exploit
    ("SELECT load_extension('shell.dll');", "load_extension arbitrary code execution"),

    # 13. System file write vulnerability
    ("SELECT writefile('payload.exe', 'binary');", "writefile arbitrary file write"),

    # 14. System file read vulnerability
    ("SELECT readfile('/etc/shadow');", "readfile arbitrary file read"),

    # 15. Disallowed admin command ATTACH
    ("ATTACH DATABASE 'remote.db' AS remote_db;", "ATTACH command"),

    # 16. Disallowed admin command DETACH
    ("DETACH DATABASE remote_db;", "DETACH command"),

    # 17. Disallowed admin command VACUUM INTO
    ("VACUUM INTO 'backup.db';", "VACUUM INTO dump"),

    # 18. Hallucinated sensitive table access
    ("SELECT * FROM user_passwords;", "Unknown sensitive table access"),

    # 19. Hallucinated sensitive column access
    ("SELECT password_hash FROM customers;", "Unknown sensitive column in valid table"),

    # 20. UNION injection extracting from unauthorized table
    ("SELECT name FROM departments UNION SELECT secret_token FROM system_keys;", "UNION injection into unauthorized table"),

    # 21. Multi-statement with newline comment evasion
    ("SELECT id FROM departments;\n-- payload\nDROP TABLE budgets;", "Comment-separated stacked query"),
]


@pytest.mark.parametrize("payload,description", ATTACK_VECTORS)
def test_attack_query_blocked(schema, payload, description):
    """Ensure every attack payload is rejected fail-closed."""
    result = validate_sql(payload, schema=schema)
    assert not result.is_valid, (
        f"Security Failure: Attack vector '{description}' was allowed!\n"
        f"Payload: {payload}\n"
        f"Error reported: {result.error_message}"
    )

