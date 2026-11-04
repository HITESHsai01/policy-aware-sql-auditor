"""
SQL Guardrails Module.

Provides deterministic, AST-level safety and schema verification using SQLGlot.
Enforces:
1. Exactly one SQL statement.
2. Read-only / SELECT-only queries (blocks DDL, DML, PRAGMA, administrative operations, mutating CTEs).
3. Schema allowlisting (all tables and columns must exist in the live database schema).
4. Disallowed system / high-risk functions (e.g. load_extension).
5. Strict fail-closed semantics for invalid/unparseable SQL.
"""

from dataclasses import dataclass, field
from typing import Optional, Set
import sqlglot
from sqlglot import exp, errors

try:
    from sql_auditor.schema_inspector import DatabaseSchema
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sql_auditor.schema_inspector import DatabaseSchema


# Disallowed SQLite / system functions
DISALLOWED_FUNCTIONS = {
    "load_extension",
    "writefile",
    "readfile",
    "edit",
    "fts3_tokenizer",
    "eval",
}

# Node types that represent mutations, DDL, or admin commands
MUTATING_OR_ADMIN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.TruncateTable,
)


@dataclass
class GuardrailResult:
    is_valid: bool
    error_message: Optional[str] = None
    tables: Set[str] = field(default_factory=set)
    columns: Set[str] = field(default_factory=set)
    ast: Optional[exp.Expression] = None


def validate_sql(
    sql: str,
    schema: Optional[DatabaseSchema] = None,
    dialect: str = "sqlite",
) -> GuardrailResult:
    """
    Validates a candidate SQL string against deterministic safety rules and schema allowlists.

    Args:
        sql: The candidate SQL query string.
        schema: Optional DatabaseSchema catalog for allowlist checks.
        dialect: SQLGlot dialect (defaults to 'sqlite').

    Returns:
        GuardrailResult indicating validity, error details, and extracted identifiers.
    """
    cleaned_sql = sql.strip()
    if not cleaned_sql:
        return GuardrailResult(is_valid=False, error_message="Empty SQL statement.")

    # 1. Single Statement Check (Reject multiple semicolons or stacked queries)
    # Check for raw semicolon injection before parsing
    # Trailing semicolon is permitted, but multiple semicolons or statements are rejected
    stripped_trailing = cleaned_sql.rstrip(";")
    if ";" in stripped_trailing:
        return GuardrailResult(
            is_valid=False,
            error_message="Multiple SQL statements detected; only single statements are permitted.",
        )

    # Parse with SQLGlot
    try:
        statements = sqlglot.parse(cleaned_sql, read=dialect)
    except errors.ParseError as pe:
        return GuardrailResult(
            is_valid=False,
            error_message=f"SQL syntax parse error: {str(pe)}",
        )
    except Exception as e:
        return GuardrailResult(
            is_valid=False,
            error_message=f"Failed to parse SQL: {str(e)}",
        )

    if not statements or len(statements) != 1 or statements[0] is None:
        return GuardrailResult(
            is_valid=False,
            error_message="Exactly one SQL statement is required.",
        )

    ast = statements[0]

    # 2. SELECT-only & Read-only enforcement
    # The root statement must be a Select or Union
    if not isinstance(ast, (exp.Select, exp.Union)):
        return GuardrailResult(
            is_valid=False,
            error_message=f"Disallowed statement type: {type(ast).__name__}. Only SELECT queries are permitted.",
            ast=ast,
        )

    # Traverse AST to ensure no nested DML, DDL, or admin nodes anywhere (including inside CTEs or subqueries)
    for node in ast.walk():
        if isinstance(node, MUTATING_OR_ADMIN_NODES):
            return GuardrailResult(
                is_valid=False,
                error_message=f"Disallowed mutating or administrative operation: {type(node).__name__}.",
                ast=ast,
            )

        # 4. Disallowed System Functions
        if isinstance(node, exp.Anonymous):
            func_name = node.name.lower()
            if func_name in DISALLOWED_FUNCTIONS:
                return GuardrailResult(
                    is_valid=False,
                    error_message=f"Disallowed function call detected: {func_name}()",
                    ast=ast,
                )
        elif isinstance(node, exp.Func):
            func_name = node.sql_name().lower()
            if func_name in DISALLOWED_FUNCTIONS:
                return GuardrailResult(
                    is_valid=False,
                    error_message=f"Disallowed function call detected: {func_name}()",
                    ast=ast,
                )

    # Collect CTE names defined in query to allow CTE references
    cte_names = {
        cte.alias_or_name.lower()
        for cte in ast.find_all(exp.CTE)
        if cte.alias_or_name
    }

    # 3. Schema Allowlist Check
    tables_found: Set[str] = set()
    table_alias_map: dict[str, str] = {}  # alias -> real_table_name

    for tbl_node in ast.find_all(exp.Table):
        tbl_name = tbl_node.name.lower()
        alias = tbl_node.alias.lower() if tbl_node.alias else tbl_name

        # Skip CTE names
        if tbl_name in cte_names:
            table_alias_map[alias] = tbl_name
            continue

        tables_found.add(tbl_name)
        table_alias_map[alias] = tbl_name

        if schema is not None:
            if not schema.has_table(tbl_name):
                return GuardrailResult(
                    is_valid=False,
                    error_message=f"Unknown table '{tbl_name}' is not in the schema allowlist.",
                    tables=tables_found,
                    ast=ast,
                )

    columns_found: Set[str] = set()

    # Verify column references against schema
    if schema is not None:
        for col_node in ast.find_all(exp.Column):
            col_name = col_node.name.lower()
            # Wildcard '*' is not a specific column name
            if col_name == "*":
                continue

            columns_found.add(col_name)
            col_table = col_node.table.lower() if col_node.table else None

            if col_table:
                # Column is qualified with table name or alias (e.g. expenses.amount or e.amount)
                resolved_table = table_alias_map.get(col_table, col_table)
                if resolved_table in cte_names:
                    # Column from CTE, accepted
                    continue
                if not schema.has_table(resolved_table):
                    return GuardrailResult(
                        is_valid=False,
                        error_message=f"Column '{col_name}' references unknown table or alias '{col_table}'.",
                        tables=tables_found,
                        columns=columns_found,
                        ast=ast,
                    )
                if not schema.has_column(resolved_table, col_name):
                    return GuardrailResult(
                        is_valid=False,
                        error_message=f"Unknown column '{col_name}' does not exist in table '{resolved_table}'.",
                        tables=tables_found,
                        columns=columns_found,
                        ast=ast,
                    )
            else:
                # Unqualified column name: verify it exists in at least one referenced table or CTE
                exists_in_any = False
                for tbl_name in tables_found:
                    if schema.has_column(tbl_name, col_name):
                        exists_in_any = True
                        break
                if not exists_in_any and not cte_names:
                    return GuardrailResult(
                        is_valid=False,
                        error_message=f"Unknown column '{col_name}' not found in any referenced table: {sorted(tables_found)}.",
                        tables=tables_found,
                        columns=columns_found,
                        ast=ast,
                    )

    return GuardrailResult(
        is_valid=True,
        tables=tables_found,
        columns=columns_found,
        ast=ast,
    )
